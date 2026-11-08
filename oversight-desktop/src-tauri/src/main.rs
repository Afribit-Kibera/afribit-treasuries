//! Afribit Oversight: the window around the oversight core.
//!
//! The screens (../src) can call one command, `core`. It passes a request to the bundled
//! Python core (clans.oversight_service) as one JSON line and returns its answer. Every check,
//! the key and the records stay in the core. This shell only:
//!
//! * starts the core with an absolute path and `python -I`, never through a shell;
//! * passes on only the command names the core knows;
//! * keeps the window on the app's own pages, and hides it from screenshots.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::fs::{self, OpenOptions};
use std::io::{self, BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};
use std::sync::Mutex;

use serde::Serialize;
use serde_json::{json, Value};
use tauri::{AppHandle, Manager, Url, WebviewUrl, WebviewWindowBuilder};

/// Server built into this installer. Empty: the app asks on first start.
const CLANS_URL: &str = match option_env!("OVERSIGHT_CLANS_URL") {
    Some(url) => url,
    None => "",
};

/// The commands in clans.oversight_service.COMMANDS. The core checks them again.
const COMMANDS: &[&str] = &[
    "status",
    "create_key",
    "restore_key",
    "check_passphrase",
    "check_words",
    "connect",
    "admin_lines",
    "records",
    "clans",
    "funding_address",
    "overview",
    "alarms",
    "mark_alarms_read",
    "register_wallet",
    "open_payout",
    "confirm_address",
    "approve",
];

const CREATE_NO_WINDOW: u32 = 0x0800_0000;
const DEV_PORT: u16 = 5178;

#[derive(Debug, Serialize)]
struct CoreError {
    error: String,
    code: String,
    /// Which check failed, for the screens to handle in their own way (see the core's `Check`).
    #[serde(skip_serializing_if = "Option::is_none")]
    reason: Option<String>,
}

fn refused(message: &str) -> CoreError {
    CoreError {
        error: message.into(),
        code: "refused".into(),
        reason: None,
    }
}

fn stopped() -> CoreError {
    CoreError {
        error: "The oversight core stopped. Nothing was signed unless the app said it was \
                approved. Close and reopen the app, and tell the team if it happens again."
            .into(),
        code: "core_stopped".into(),
        reason: None,
    }
}

struct Core {
    child: Child,
    stdin: ChildStdin,
    stdout: BufReader<ChildStdout>,
    next: u64,
}

impl Core {
    fn exchange(&mut self, line: &str) -> io::Result<String> {
        self.stdin.write_all(line.as_bytes())?;
        self.stdin.write_all(b"\n")?;
        self.stdin.flush()?;
        let mut reply = String::new();
        if self.stdout.read_line(&mut reply)? == 0 {
            return Err(io::Error::new(io::ErrorKind::UnexpectedEof, "the core closed"));
        }
        Ok(reply)
    }
}

impl Drop for Core {
    fn drop(&mut self) {
        let _ = self.child.kill();
    }
}

struct CoreState {
    python: PathBuf,
    home: PathBuf,
    core: Mutex<Option<Core>>,
}

impl CoreState {
    fn start(&self) -> io::Result<Core> {
        fs::create_dir_all(&self.home)?;
        // The core writes only tracebacks here, never requests.
        let log = OpenOptions::new()
            .create(true)
            .append(true)
            .open(self.home.join("app-core.log"))?;
        let mut command = Command::new(&self.python);
        command
            .args(["-I", "-m", "clans.oversight_service", "--home"])
            .arg(&self.home)
            .env_remove("PYTHONPATH")
            .env_remove("PYTHONHOME")
            .env_remove("PYTHONSTARTUP")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::from(log));
        if !CLANS_URL.is_empty() {
            command.args(["--url", CLANS_URL]);
        }
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(CREATE_NO_WINDOW);
        }
        let mut child = command.spawn()?;
        let missing = || io::Error::new(io::ErrorKind::Other, "no pipe to the core");
        let stdin = child.stdin.take().ok_or_else(missing)?;
        let stdout = BufReader::new(child.stdout.take().ok_or_else(missing)?);
        Ok(Core {
            child,
            stdin,
            stdout,
            next: 0,
        })
    }

    fn call(&self, command: &str, args: Value) -> Result<Value, CoreError> {
        let mut guard = self.core.lock().map_err(|_| stopped())?;
        let running = match guard.as_mut() {
            Some(core) => matches!(core.child.try_wait(), Ok(None)),
            None => false,
        };
        if !running {
            *guard = Some(self.start().map_err(|_| stopped())?);
        }
        let core = guard.as_mut().ok_or_else(stopped)?;
        core.next += 1;
        let id = core.next;
        let line = json!({"id": id, "command": command, "args": args}).to_string();
        let answer = core
            .exchange(&line)
            .ok()
            .and_then(|text| serde_json::from_str::<Value>(&text).ok())
            .filter(|answer| answer.get("id").and_then(Value::as_u64) == Some(id));
        let Some(answer) = answer else {
            // Out of step with the core: start a fresh one next time.
            *guard = None;
            return Err(stopped());
        };
        if answer.get("ok") == Some(&Value::Bool(true)) {
            return Ok(answer.get("result").cloned().unwrap_or(Value::Null));
        }
        let text = |name: &str, fallback: &str| {
            answer
                .get(name)
                .and_then(Value::as_str)
                .unwrap_or(fallback)
                .to_string()
        };
        Err(CoreError {
            error: text("error", "The core refused this"),
            code: text("code", "internal"),
            reason: answer
                .get("reason")
                .and_then(Value::as_str)
                .map(str::to_string),
        })
    }
}

#[tauri::command]
async fn core(app: AppHandle, command: String, args: Value) -> Result<Value, CoreError> {
    if !COMMANDS.contains(&command.as_str()) {
        return Err(refused("Unknown command"));
    }
    if !(args.is_object() || args.is_null()) {
        return Err(refused("The arguments must be an object"));
    }
    let args = if args.is_null() { json!({}) } else { args };
    // Signing and server calls can take seconds; keep them off the window's thread.
    tauri::async_runtime::spawn_blocking(move || app.state::<CoreState>().call(&command, args))
        .await
        .map_err(|_| stopped())?
}

/// Only the app's own pages. In a debug build, also the Vite dev server.
fn allowed(url: &Url) -> bool {
    let host = url.host_str();
    match url.scheme() {
        "tauri" => true,
        "http" | "https" if host == Some("tauri.localhost") => true,
        "http" if cfg!(debug_assertions) => {
            host == Some("127.0.0.1") && url.port() == Some(DEV_PORT)
        }
        _ => false,
    }
}

fn data_folder(app: &AppHandle) -> tauri::Result<PathBuf> {
    // The same folder as the console app, so an existing laptop keeps its key and records.
    match std::env::var_os("LOCALAPPDATA") {
        Some(base) => Ok(PathBuf::from(base).join("AfribitOversight")),
        None => Ok(app.path().local_data_dir()?.join("AfribitOversight")),
    }
}

fn python(app: &AppHandle) -> tauri::Result<PathBuf> {
    #[cfg(debug_assertions)]
    if let Some(path) = std::env::var_os("OVERSIGHT_PYTHON") {
        return Ok(PathBuf::from(path));
    }
    Ok(app
        .path()
        .resource_dir()?
        .join("python")
        .join("python.exe"))
}

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![core])
        .setup(|app| {
            let handle = app.handle();
            app.manage(CoreState {
                python: python(handle)?,
                home: data_folder(handle)?,
                core: Mutex::new(None),
            });
            WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                .title("Afribit Oversight")
                .inner_size(1100.0, 760.0)
                .min_inner_size(900.0, 640.0)
                .center()
                // Keeps the backup words and payouts out of screenshots and screen sharing.
                .content_protected(true)
                .on_navigation(allowed)
                .build()?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("Afribit Oversight couldn't start");
}
