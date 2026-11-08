import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";
import type { IncomingMessage, ServerResponse } from "node:http";

const here = path.dirname(fileURLToPath(import.meta.url));
const PORT = 5178;
const MAX_BODY = 64 * 1024;

type Reply = { id?: unknown; ok: boolean; result?: unknown; error?: string; code?: string };
type Job = { line: string; id: number; done: (reply: Reply) => void };

/**
 * Dev only: POST /__core forwards one request to a long-lived Python core, the way the Rust
 * shell does in the app. One request in flight at a time; replies matched by id.
 *
 * It needs OVERSIGHT_DEV_HOME, so nobody points dev at a real laptop's
 * %LOCALAPPDATA%\AfribitOversight by accident. Arguments are never logged.
 */
function coreBridge(): Plugin {
  const home = process.env.OVERSIGHT_DEV_HOME;
  const python = process.env.OVERSIGHT_PYTHON || path.resolve(here, "../.venv/Scripts/python.exe");
  const url = process.env.OVERSIGHT_DEV_URL || "http://127.0.0.1:8410";
  let child: ChildProcessWithoutNullStreams | null = null;
  let buffer = "";
  let nextId = 1;
  const queue: Job[] = [];
  let current: Job | null = null;

  function stopped(error: string): Reply {
    return { ok: false, error, code: "core_stopped" };
  }

  function start() {
    buffer = "";
    const proc = spawn(python, ["-m", "clans.oversight_service", "--home", home!, "--url", url], {
      cwd: here,
      env: { ...process.env, PYTHONPATH: path.resolve(here, "../backend/src"), PYTHONUTF8: "1" },
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
    });
    proc.stdout.setEncoding("utf8");
    proc.stderr.setEncoding("utf8");
    proc.stdout.on("data", (chunk: string) => {
      buffer += chunk;
      let end: number;
      while ((end = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, end).trim();
        buffer = buffer.slice(end + 1);
        if (!line || !current) continue;
        let reply: Reply;
        try {
          reply = JSON.parse(line) as Reply;
        } catch {
          reply = stopped("The core sent an unreadable answer");
        }
        if (reply.id !== current.id) continue; // not the answer we wait for
        const job = current;
        current = null;
        job.done(reply);
        pump();
      }
    });
    // The core's own errors (tracebacks). Never the request, which may hold a passphrase.
    proc.stderr.on("data", (chunk: string) => process.stderr.write(`[core] ${chunk}`));
    const gone = (why: string) => {
      if (child !== proc) return;
      child = null;
      const job = current;
      current = null;
      job?.done(stopped(`The core stopped (${why})`));
      pump();
    };
    proc.on("exit", (code) => gone(`exit ${code}`));
    proc.on("error", (error) => gone(error.message));
    child = proc;
  }

  function pump() {
    if (current || !queue.length) return;
    if (!child) start();
    current = queue.shift()!;
    child!.stdin.write(current.line + "\n");
  }

  function send(command: unknown, args: unknown): Promise<Reply> {
    return new Promise((done) => {
      const id = nextId++;
      queue.push({ id, line: JSON.stringify({ id, command, args: args ?? {} }), done });
      pump();
    });
  }

  function answer(res: ServerResponse, status: number, body: Reply) {
    res.statusCode = status;
    res.setHeader("Content-Type", "application/json");
    res.setHeader("Cache-Control", "no-store");
    res.end(JSON.stringify(body));
  }

  function sameOrigin(req: IncomingMessage) {
    const allowed = [`http://127.0.0.1:${PORT}`, `http://localhost:${PORT}`];
    const host = req.headers.host || "";
    const origin = req.headers.origin;
    return (
      [`127.0.0.1:${PORT}`, `localhost:${PORT}`].includes(host) &&
      (!origin || allowed.includes(origin)) &&
      (req.headers["content-type"] || "").startsWith("application/json")
    );
  }

  return {
    name: "oversight-core-bridge",
    apply: "serve",
    configureServer(server) {
      server.httpServer?.on("close", () => child?.kill());
      server.middlewares.use("/__core", (req, res) => {
        if (req.method !== "POST") return answer(res, 405, stopped("Use POST"));
        if (!sameOrigin(req)) return answer(res, 403, stopped("Refused: not from this app"));
        if (!home)
          return answer(
            res,
            503,
            stopped(
              "Set OVERSIGHT_DEV_HOME to a test folder before npm run dev. Dev never uses a real laptop's data folder",
            ),
          );
        let body = "";
        let tooLong = false;
        req.setEncoding("utf8");
        req.on("data", (chunk: string) => {
          body += chunk;
          if (body.length > MAX_BODY) tooLong = true;
        });
        req.on("end", () => {
          if (tooLong) return answer(res, 413, stopped("The request is too long"));
          let parsed: { command?: unknown; args?: unknown };
          try {
            parsed = JSON.parse(body);
          } catch {
            return answer(res, 400, stopped("The request isn't valid JSON"));
          }
          void send(parsed.command, parsed.args).then((reply) => {
            const { id: _id, ...rest } = reply;
            answer(res, 200, rest);
          });
        });
      });
    },
  };
}

export default defineConfig({
  root: here,
  base: "./",
  plugins: [react(), coreBridge()],
  resolve: {
    // Files shared from ../frontend/src use this folder's copies, so the build needs no
    // frontend/node_modules.
    dedupe: ["react", "react-dom", "@phosphor-icons/react"],
  },
  build: {
    outDir: path.resolve(here, "dist"),
    emptyOutDir: true,
    modulePreload: { polyfill: false },
    sourcemap: false,
  },
  server: {
    host: "127.0.0.1",
    port: PORT,
    strictPort: true,
    fs: { allow: [here, path.resolve(here, "../frontend/src")] },
  },
});
