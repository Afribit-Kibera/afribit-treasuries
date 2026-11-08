# The oversight desktop app: proposal

**For:** the product owner, who decides, and the engineers who'll build it.
**Status:** test version built, 6 November 2026. The app covers setting up a laptop, connecting, alarms, registering clan wallets, and checking and approving payouts, on mainnet and test networks. It hasn't been tried on a real oversight laptop yet. Still to build: the report screen, record backup and restore, editing limits, and updating from a file. A reviewer should also check that the WebView2 debugging setting (`WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS`) can't be used to drive the app on an oversight laptop.
**Replaces:** the guided console app (`backend/src/clans/oversight_guide.py`), installed from the offline kit ([oversight-laptop-setup.md](oversight-laptop-setup.md)).

## Recommendation

Build a **Tauri 2 desktop app** for Windows. Its screens are a small React app that uses our existing design: the same colour tokens, fonts, Phosphor icons and components as the phone app. Behind the screens, it runs **today's Python oversight code, unchanged**, as a bundled helper process. All the checks, the key and the register stay in `oversight.py`. The screens only show what that code decides and pass on what the person types. Ship it as **one `.exe` installer**, downloaded from our GitHub or website (not an app store), that works without internet, installs per user, and keeps every existing laptop's key and records. Updates arrive the way they do today, by USB, but the app checks the update's signature itself. There's no auto-update.

**Why:**

1. **The risky part is already done and tested.** `review()`, `sign()`, the wallet code check and the address check are reviewed, covered by tests and proven on mainnet. Rewriting them would mean testing and reviewing them again, for nothing the person would notice.
2. **The design already exists.** The phone app's CSS and `ui.tsx` give us the look for free, and the phone app is already built in React.
3. **Tauri's security model fits.** It enforces a content security policy, exposes only the commands we list, and adds no Node runtime. The shell is about 10 MB. The screens can't reach the network at all: only the Python core talks to the Clans server.
4. **It's the smallest change for existing laptops.** Same data folder, same key file, same server token. Nobody makes a new key, and the administrator changes nothing.

**Fallback:** if nobody on the team can own a few hundred lines of Rust, use **pywebview** instead. It's the same React screens and the same Python core, with weaker built-in hardening (see the comparison).

Rough size: **7 to 10 engineer-weeks** over three phases. Phase A (about 3 to 4 weeks) puts the three screens people use most in front of the existing laptops on signet.

---

## 1. What's wrong with the console today

These are from `oversight_guide.py`, the setup guide and the mainnet trial.

**Installing and opening**

- The person checks the kit by running `Get-FileHash` in PowerShell, then comparing 64 hex characters by eye with a message.
- The installer and launcher are unsigned `.cmd` files. Windows says "Windows protected your PC", and the guide tells people to choose **More info → Run anyway**. That teaches the habit we least want in a key holder.
- The app is a black console window. A mistyped key or a closed window ends the session ("Closed. Nothing was signed unless it said 'Approved and sent'").

**Moving around**

- **Enter means different things.** On the main screen it does the first choice. During a payout it skips. At the wallet code prompt it means "do this later". People learn to press Enter to get past things.
- **The app goes straight into everything waiting** when it opens. The person can't first see a list of what's waiting, choose one, or go back. Payouts come one at a time, in a fixed order.
- **Nothing refreshes by itself.** The person presses "Check again". In the mainnet trial, repeated checks used up the laptop's 120 server calls an hour.

**The checks**

- **The address check** asks for "the 12 characters they read" in one box, first 6 then last 6. One typo, and that payout is dropped until the next session.
- **The wallet code** gets two tries, then the registration fails for that session.
- **Large payouts** need the total typed in sats, digit for digit. There's no KES figure anywhere.
- **The passphrase** is typed blind, with no caps-lock warning and no way to show it.

**What it shows**

- Raw technical text: a 64-character transaction id, full addresses, "Network fee: 228 sats, paid by the beneficiaries".
- Alarm codes such as `unapproved_spend`, with details as `key=value`. Errors such as "Clans refused this (429): …" and "Couldn't reach Clans (ConnectTimeout)".
- **It never says which network a payment is on.** A test payment and a real-money payment look the same.
- Nothing separates what the laptop checked itself from what the server merely says.

**What's missing**

- No community report screen, though `GET /api/oversight/report` exists.
- No real history. "This laptop's records" shows the last 10 approvals as sats, and lists addresses raw.
- Backing up records means "Copy `register.json` to a USB stick now and then". There's no reminder and no way to restore it in the app.
- Restoring a key means typing R at a prompt, then all 12 words, hidden, on one line. There's no word-by-word check.
- Limits, the clan backup file and offline approval exist only as commands.
- There's no version shown in the app, and no help for updating.

---

## 2. What the oversight person does, screen by screen

One window, about 1,100 × 750, which also works on a 1366 × 768 laptop. It opens in dark theme, or follows Windows. It has a left rail with **Home**, **Alarms**, **Report**, **Clans** and **This laptop**.

A band across the top always shows the community, the connection, and the **network**:

- "Test network: not real money", in a striped band, on signet or testnet.
- "Bitcoin: real money", in a plain band, on mainnet.

**Two kinds of fact, shown differently.** Every screen marks:

- **checked by this laptop**, with a filled tick (the amount each person receives, the address, the wallet, the fee limit);
- **from Clans**, with an outline info icon (grant purpose, names, votes).

The person learns that only ticked facts are guaranteed. This is the most important UX idea in the proposal. It turns "trust the laptop, not the server" into something people can see.

**What stays the same everywhere:**

- Nothing is ever signed without the passphrase.
- **Enter never approves and never skips.** Each action is a button with its own words: "Approve with passphrase", "Skip for now", "Stop and report".
- Every refusal from the core is shown word for word, with what to do next.

### 2.1 First-run setup

There are four steps, with a progress row ("Step 2 of 4"). Each step can go back until the key exists.

1. **Welcome.** "Make a new oversight key" or "I have 12 backup words". It explains in one paragraph what the key is for.
2. **Your 12 words.**
   - Words show in a 3 × 4 grid with numbers.
   - The window is protected from screenshots while they show (Tauri's `contentProtected`).
   - "I've written them down" leads to a check: three randomly chosen word boxes. It's three, up from today's two, because now nothing needs typing blind.
   - **Restoring** uses 12 separate boxes with suggestions from the BIP-39 word list, and a checksum check before going on.
3. **Your passphrase.**
   - At least 12 characters, with a strength hint ("4 or 5 random words").
   - A show/hide eye, a caps-lock warning, and type-it-again.
4. **The file for your community.**
   - The app connects to the Clans address built into the installer, or asks for it if the installer has none, then shows the public lines (laptop name, test and mainnet public keys, connection line).
   - Buttons: **Save to desktop** (as today) and **Copy**.
   - It says plainly: "These lines are safe to send. They can't approve anything."
   - The home screen then says "Waiting for <community> to add this laptop" until the server stops answering 401 or 503.

```
┌───────────────────────────────────────────────────────────────┐
│  Step 2 of 4 · Your 12 backup words                           │
│                                                               │
│  Write these on paper, in order, with their numbers.          │
│                                                               │
│    1 orbit     5 lizard     9 cabin                           │
│    2 sunny     6 velvet    10 rescue                          │
│    3 maple     7 harbor    11 tiny                            │
│    4 ankle     8 glory     12 pledge                          │
│                                                               │
│  ⚠ Never photograph them or type them anywhere else.         │
│    Anyone with them can approve payouts as you.               │
│                                                               │
│  [ Back ]                           [ I've written them down ]│
└───────────────────────────────────────────────────────────────┘
```

**What changes:** the steps can go back, nothing is typed blind, restore checks each word, and the file for Afribit has buttons rather than a pause.

### 2.2 Home

Home lists everything waiting, in the order it should be done. The app refreshes it when it opens, every 5 minutes while it's open, and when "Check now" is pressed. A full refresh is 4 calls, so a refresh every 5 minutes uses 48 of the 120 calls an hour.

```
┌──────────┬────────────────────────────────────────────────────┐
│ ◉ Home   │ ▒▒ Test network: not real money ▒▒  Kibera Savers │
│ ⚠ Alarms │                                                    │
│ ▤ Report │  ⚠ 1 new alarm. Read it before approving.  [Read] │
│ ◎ Clans  │                                                    │
│ ⚙ Laptop │  Waiting for you                                   │
│          │  ┌──────────────────────────────────────────────┐ │
│          │  │ Kibera Real Sats · Grant to Juma             │ │
│          │  │ 2,530 sats · signed by 2 of 3 · 3 h ago      │ │
│          │  │ ☎ First payment to this address: phone Juma │ │
│          │  │                                  [ Review ] │ │
│          │  └──────────────────────────────────────────────┘ │
│          │  ┌──────────────────────────────────────────────┐ │
│          │  │ Mama Mboga Group · New wallet to register    │ │
│          │  │ ☎ Phone a signatory for the wallet code     │ │
│          │  │                                [ Register ] │ │
│          │  └──────────────────────────────────────────────┘ │
│          │                                                    │
│          │  Last checked 10:42 · [ Check now ]                │
└──────────┴────────────────────────────────────────────────────┘
```

- **Nothing waiting:** a large, calm "Nothing is waiting for you", the last check time, and the last approval ("You approved 2,530 sats for Juma on 6 Nov").
- **Unread alarms** sit above everything as a banner. While an alarm is unread, the **Approve** button for that clan is disabled, and the card says why. Today the app has the same rule but applies it to the whole session.
- **Problems** are plain: "Can't reach Clans. Check the internet and try again", "Waiting for Afribit to add this laptop", "Clans is busy. The app will try again in a few minutes" (for a 429). The technical detail sits behind a "Details" toggle for the team.

**What changes:** the person sees the whole list first and chooses. Nothing starts by itself, and it refreshes on its own.

### 2.3 Review and approve a payment

This is the most important screen. It has three parts, top to bottom: **phone checks still needed**, **what's being paid**, and **approve**.

**a. Phone checks, if any.** These are the same two checks as today, done inline, before the amounts unlock.

The **address check:**

```
┌───────────────────────────────────────────────────────────────┐
│  ☎ Check Juma's address by phone                              │
│                                                               │
│  This is the first payment to this address.                   │
│  1. Phone Juma.                                               │
│  2. Ask him to open HIS OWN wallet app and find the address   │
│     he gave for this grant.                                   │
│  3. Ask him to read the 6 characters right after  bc1q        │
│     and then the last 6 characters.                           │
│                                                               │
│  After bc1q   [ _ _ _ _ _ _ ]      Last 6   [ _ _ _ _ _ _ ]   │
│                                                               │
│  [ Check ]          [ He read something different: stop ]     │
└───────────────────────────────────────────────────────────────┘
```

- **The screen never shows the expected characters.** The person types what they hear, and the core compares. This is the same as today.
- There are 6 boxes each, with the cursor jumping between them. Spaces and capital letters don't matter.
- If they don't match, the app says "That doesn't match. Ask Juma to read it again, slowly" and allows 3 tries. After that, or after "stop", it says: "Don't approve this payout. Tell the clan and the team." The payout stays waiting.
- **The wallet code check** for a new clan wallet works the same way: 8 boxes, the script, and 3 tries.

**b. What's being paid**, once the checks pass:

```
┌───────────────────────────────────────────────────────────────┐
│  Kibera Real Sats · Grant payment                             │
│                                                               │
│  ✔ Juma receives        2,302 sats                            │
│    ✔ to bc1q 7xk2m9 … 4hq8zt   (checked by phone, 6 Nov)      │
│  ✔ Grant approved       2,530 sats                            │
│  ✔ Network fee            228 sats, taken from the grant      │
│  ✔ Change goes back to the clan's own wallet                  │
│                                                               │
│  ⓘ From Clans: "Kiosk stock", asked by Juma, 2 votes for     │
│                                                               │
│  Does this match what you know about this grant?              │
└───────────────────────────────────────────────────────────────┘
```

- Amounts are in sats, in the money font. Whether to add KES is an open question (see the end).
- A higher-fee replacement shows as "A higher-fee version of a payment you approved on 6 Nov. Only one of the two can ever go through."
- **Moves and refreshes** show "No beneficiary: the money stays in the clan's own wallets", and where it goes, in words.
- The transaction id and full address sit behind "Technical details".

**c. Approve:**

- **[ Approve with passphrase ]** opens a dialog with the passphrase box (show/hide, caps-lock warning).
- For large payouts, the dialog first asks for the total: "Type the total approved: 2,530 sats". Commas and spaces are fine.
- Wrong passphrase: "That passphrase is wrong" and 3 tries, as today.
- **Success:** a full-width confirmation: "Approved and sent. Clans sends the payment within a minute." It shows the signature count and a "Back to home" button.
- **[ Skip for now ]** signs nothing and leaves it waiting.
- **[ Stop and report ]** signs nothing. It shows who to tell and copies a short reference (clan, payout id) for the message.

**What changes:**

- The address check has 12 boxes in two groups, with retries.
- The person sees every fact before deciding, with ticks showing what the laptop proved.
- Approving, skipping and stopping are three separate buttons. Enter does none of them.

### 2.4 Alarms

This is a list, newest first, unread in bold. Each alarm card has:

- **A plain title and icon per kind**, for example "Money left a clan wallet without Clans" for `unapproved_spend`, or "A phone saw a different wallet code" for `wallet_code_mismatch`. Unknown kinds show the server's `message`.
- **What to do**, for example "Don't approve anything for this clan until the team has found out what happened. Phone <team contact>."
- The clan, the wallet generation and the time, as "2 hours ago" with the exact time on hover. `detail` is behind "Details".
- **[ I've read this ]** marks it read on this laptop (`mark_alarms_read`, as today).

A filter switches between unread and all. "All" shows the latest 200, as `alarms --all` does today.

### 2.5 Community report

This screen comes from `GET /api/oversight/report`.

```
┌──────────────────────────────────────────────────────────────┐
│  Report · Kibera Savers        [ November 2026 ▾ ]  [Custom] │
│                                                              │
│  4 clans · 31 members · 22 active                            │
│  Paid out 12,400 sats · Repaid 9,800 · Still owed 2,600      │
│                                                              │
│  Clan               Members Active Paid out Repaid Owed Rate │
│  Kibera Real Sats      3      3     2,530  2,190   340  87%  │
│  Mama Mboga Group     12      9     6,000  5,000 1,000  83%  │
│  …                                                           │
│                                                              │
│  [ Save as spreadsheet (CSV) ]   [ Print ]                   │
└──────────────────────────────────────────────────────────────┘
```

- The period is a month picker, or a custom period of up to 366 days. `to` is exclusive in the API, and the screen hides that.
- A clan with security activity, or with an unread alarm, gets a warning dot that links to Alarms.
- **Save as spreadsheet** opens Windows' save dialog. The core writes the file (`format=csv`), so the screens never get file system access.
- The report names clans, never members. That's the server's rule, and the screen adds nothing.

### 2.6 Clans: wallet registration and funding addresses

This lists the clans registered on this laptop: name, wallet generation, wallet code, signatories ("2 of 3"), and the date it was registered.

- **New or moved wallets** show "Register" and use the wallet code check from 2.3.
- **Funding address** shows the clan address worked out from the registered wallet, never from the server.
  - It's shown large, with the 6 characters after the start and the last 6 highlighted.
  - It has a Copy button and a QR code. The QR comes from the core's address, drawn locally.
  - It says: "On the sending wallet, check these 12 characters match."
- **Save the clan's backup file** (`export-backup`) uses the save dialog.
- **Confirmed addresses** lists names and short addresses, with the date each was checked by phone.

### 2.7 This laptop: backups, settings, updates

**Back up this laptop's records.**

- This saves `register.json` to a chosen folder, usually a USB stick, with the date in the file name. It holds no secret.
- The app reminds the person on the home screen after 10 approvals, or 30 days since the last backup.
- **Restore records** reads a backup, shows what it holds ("3 clans, 7 addresses, 12 approvals, saved 2 Nov"), and replaces only after a confirmation.
- **The core merges rather than overwrites approvals.** That way a restore can never forget a grant already paid. This is a small core change; see Security.

**The oversight key.**

- **Check my paper backup:** type 3 random words. The core checks them against the sealed words, which needs the passphrase. This is new; it catches lost or wrong paper before it's needed.
- **Change passphrase:** this seals the same words again. It's a small core addition.
- **Restore from 12 words** on a new laptop is the same screen as first-run restore.
- **The file for your community:** the admin lines again, with Save and Copy.

**Limits.** This shows `max_fee_sats`, `max_sweep_fee_sats` and `large_payout_sats` with plain labels. Changing a limit needs the passphrase, because raising one weakens a check. That's new: today `set-limits` needs nothing.

**About and updates.**

- This shows the version, commit, network and Clans address.
- **Install an update from a file:**
  1. The person picks the new installer from the USB stick.
  2. The app checks its signature (section 4.5) and shows "Afribit Oversight 1.3.0, signed by Afribit on 2 Dec".
  3. It offers **Install**. A file that doesn't pass is refused, with "Don't install this. Ask the team for a new copy."

**What changes:** backup, restore, checking the paper and updating were all manual file work. Now each is a button with a check behind it.

### 2.8 Kept as commands, not screens

**Offline approval** (`review`, `sign --out`, `upload`), `status` and the raw commands stay in the Python tool, which the installer still ships, for administrators and for working without a connection. A later version could add "Approve from a file". The current trial shows no need for it.

---

## 3. Technology options

The facts were checked on 6 November 2026. Versions are the latest found in each project's own pages and changelogs.

- **Tauri** 2.11.x (2.11.5, 1 July 2026). The shell plugin is at 2.3.x.
- **pywebview** 6.x (6.2.1 is the latest seen). It added bundling a WebView2 runtime in 6.1.
- **bdkpython** 3.1.1 is what we use. The official BDK bindings (bdk-ffi) are Kotlin, Swift and Python only. There's no official JavaScript binding. The WASM build is MetaMask's `@metamask/bitcoindevkit`, 0.1.x (latest seen August 2025), which supports only Esplora as a chain source. Rust has `bdk_wallet` natively.
- **Electron** releases a major version every 8 weeks and supports only the latest three.
- **WebView2** (which Tauri and pywebview use) is part of Windows 11. Tauri's NSIS installer can embed the offline WebView2 installer (about 127 MB more) or a fixed runtime (about 180 MB more), so install works with no internet. It installs per user by default (`%LOCALAPPDATA%`, no admin rights).

| | **1. Tauri + React + Python core (recommended)** | **2. Tauri or Electron, signing rewritten in Rust (BDK) or TypeScript** | **3. pywebview + React + Python core** | **3b. PySide6 (Qt) + Python core** | **4. Electron + React + Python core** |
|---|---|---|---|---|---|
| **Reuses the Python core** | All of it, unchanged. A thin service layer is added | None. About 1,000 lines plus tests rewritten. The key file format must be re-implemented to keep existing keys | All of it, in-process | All of it, in-process | All of it, as a helper process |
| **Reuses the React UI and design** | Yes: tokens, fonts, Phosphor, `ui.tsx` patterns | Yes | Yes | No. Native Qt widgets need the design redone in QSS. QtWebEngine would add about 150 MB of Chromium | Yes |
| **Where checks run** | Python (`review()`), the single source of truth | New code. TypeScript would reuse the **phone's** `vault/sign.ts`, which removes today's independence between the phone's check (scure) and the laptop's (BDK) | Python | Python | Python |
| **Key storage** | Unchanged file, optional DPAPI layer | Re-implemented (scrypt + AES-GCM) | Unchanged | Unchanged | Unchanged |
| **What the screens can call** | Only the listed commands, per window (capabilities). Strong CSP enforced. No Node | Same as 1 for Tauri. For Electron, see 4 | Every public method on one Python object exposed to JavaScript. CSP and navigation locks are ours to add | No web layer | Node in the main process. Safe only with `contextIsolation`, `sandbox` and no `nodeIntegration`, kept right in every release |
| **Auto-update risk** | Updater plugin exists, but we don't enable it | Same | None built in | None built in | `electron-updater` is common, and tempting |
| **Supply chain** | Rust crates (Cargo.lock), a few npm packages, 3 Python wheels | Rust crates or npm, plus a new crypto stack to vet | Python wheels plus pythonnet / .NET bridge | Qt (LGPL), PySide wheels | Chromium + Node + the npm tree. The 8-week majors mean frequent forced updates to a USB-updated laptop |
| **Installer size** (estimate) | About 35 MB. About 160 MB with offline WebView2 | About 15 MB (Rust). About 140 MB with WebView2 | About 40 MB, plus WebView2 if missing | 70–100 MB | About 120 MB including Python |
| **Offline install** | Yes (NSIS + WebView2 offline installer) | Yes | Yes. WebView2 via 6.1 runtime bundling, or Windows 11's own | Yes | Yes |
| **A real `.exe` and signing** | NSIS installer and app exe, which can be Authenticode-signed (we decided not to). Python from python.org is already signed by the PSF | Yes | Needs a frozen exe (PyInstaller, which antivirus tools often flag) or a stub launcher | Same as 3 | Yes |
| **Effort** (engineer-weeks) | **7–10** | 11–16, plus a new security review of the signing code | 6–9 | 9–12 | 8–11 |

**Why not the others:**

- **Rewriting the signing (2)** throws away the most valuable thing we have: checks that are reviewed, tested and proven on mainnet. Each rewritten line is a new place to get "trust the laptop, not the server" wrong. The TypeScript route is worse still. The phone and the laptop would then share one implementation, so a bug that fools the phone's check would also fool the laptop's. A Rust/BDK core is a sensible **later** step (Phase D, below) if the Python runtime becomes a burden. It isn't the first step.
- **pywebview (3)** is the honest runner-up. It's a bit less work and has one language fewer. But it has no capability system, no enforced CSP and no navigation lock. Its JavaScript-to-Python bridge exposes a whole object. Producing a proper `.exe` means PyInstaller or a launcher stub. Pick it only if there's no Rust owner.
- **PySide (3b)** loses the design, which the product owner asked to keep.
- **Electron (4)** is the biggest, has the most to keep patched, and invites auto-update. That's the wrong shape for a key-holding laptop updated by USB.

**How option 1 fits together:**

```
┌───────────────────────── Afribit Oversight.exe (Tauri) ─────────────────────────┐
│  WebView2: React screens            Rust shell (~300 lines)                     │
│  no network, strict CSP     IPC     • fixed list of commands                    │
│  shows Review results     ───────►  • starts the core, one JSON line per call   │
│  sends: ids, typed codes,           • save/open dialogs, window protection      │
│  passphrase                         • no shell / fs / http plugins enabled      │
└─────────────────────────────────────────────┬───────────────────────────────────┘
                                              │ stdin/stdout, JSON lines
                         ┌────────────────────▼─────────────────────┐
                         │ bundled python.exe -I -m clans.oversight_service │
                         │  wraps oversight.py: review(), sign(),           │
                         │  add_wallet(), confirm_address(), unlock()...    │
                         │  the ONLY thing that talks to the Clans server   │
                         └──────────────────────────────────────────────────┘
```

- The Python folder ships as a Tauri **resource**, as today's kit does. It's not a PyInstaller one-file sidecar, which unpacks into a temp folder and gets flagged by antivirus.
- The Rust shell starts it itself, with an absolute path. That way the shell plugin, and its `shell:allow-execute` permission, is never enabled for the screens.
- The core gets its own small package: `bdkpython`, `cryptography`, `httpx`, and the `clans.oversight`, `clan_wallet` and `recover` modules. Today's kit installs the whole backend wheel, with FastAPI, SQLAlchemy, psycopg, uvicorn and webauthn, which the laptop never uses.

---

## 4. Security design

### 4.1 The key

- **The file stays the same:** `%LOCALAPPDATA%\AfribitOversight\oversight-key.json`, the 12 words sealed with AES-GCM under a scrypt key (`n=2^17`) from the passphrase. Existing keys work as they are.
- **Optional extra layer: Windows DPAPI.** The core can wrap the file with `CryptProtectData` (user scope), so a copy taken off the laptop also needs the Windows account's login.
  - It doesn't help against malware running inside the oversight account, which is the risk the setup guide names.
  - A Windows password **reset** by an administrator (not a normal change) makes the file unreadable. The person then restores from the 12 words.
  - Recommendation: offer it in Phase B, default on for new keys, with the restore path explained on screen. This is an open question.
- **The words are shown once**, with screenshot protection. They're never copied to the clipboard and never written to logs.
- **The passphrase** goes from the input box, through IPC, to the core, and is used and dropped. It's never stored. Python can't reliably wipe a string from memory. That's true today too, and it should be listed for the reviewer.
- **A signer interface.** `sign()` gets the key through one function, so a Ledger can replace the software key later without changing the screens.

### 4.2 Only one thing talks to the network

- **The screens have no network access:** `connect-src` allows only Tauri's IPC. All server calls come from the core, to the one address in `server.json`, over HTTPS (the existing rule in `connect()`), with redirects refused (`follow_redirects=False`, as today).
- **The content security policy:** `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src ipc: http://ipc.localhost; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'`.
- **Fonts are bundled** (Fontsource, as the phone app does). Nothing comes from Google Fonts or any CDN.
- **No remote code:**
  - The app never navigates away from its own pages. Tauri's navigation handler blocks every other URL.
  - It opens no external links. The block explorer link is shown as text to copy.
  - Dev tools are off in release builds.
  - No `eval`.
- **Tauri plugins:** only the dialog plugin, for save and open. No shell, fs, http, updater or opener plugin. The capability file lists only our commands.

### 4.3 The IPC surface

The screens can call about 20 named commands, each a thin wrapper over a core function. The Rust shell rejects any other name, and the core checks every argument again.

| Command | Core function |
|---|---|
| `overview` | `pending`, `unread_alarms`, `unregistered`, community name |
| `review_payout(id)` | Fetches the payout, runs `review()`, returns the `Review` |
| `register_wallet(clan_id, code)` | `add_wallet` with the server's wallet, as `register_from_server` does |
| `confirm_address(payout_id, line, start, end)` | `confirm_address`. The address comes from the core's copy of the payout, never from the screen |
| `approve(id, passphrase, typed_total, shown)` | Fetches again, `review()`, `sign()`, `upload()` |
| `alarms(all)`, `mark_alarms_read(shown)` | As today: marks read up to the newest alarm shown |
| `report(from, to)`, `save_report_csv(from, to)` | New: `GET /api/oversight/report`, written to the path from the save dialog |
| `funding_address(clan)`, `save_wallet_backup(clan)` | `clan_address`, `wallet_backup` |
| `records`, `save_records`, `restore_records` | Register backup and merge |
| `create_key`, `restore_key`, `check_words`, `change_passphrase`, `admin_lines`, `connect` | Setup |
| `get_limits`, `set_limits(passphrase, …)` | Settings |
| `verify_update(path)` | Section 4.5 |

**What the person saw is what they sign.**

- The screen never handles a PSBT. It sends a payout id.
- `approve` also sends `shown`: the `txid` and total from the review the person read.
- The core fetches the payout again and runs `review()` again (`sign()` already does). It refuses if the txid or total differs from `shown`. So a payout that changed between reading and approving is never signed.

### 4.4 What must stay identical

These stay in `oversight.py` and are called, never copied. The existing tests (`test_oversight.py`, `test_oversight_guide.py`, the `test_clan_wallet*` suites) keep passing unchanged.

- `review()` and `_review_sweep()`: the registered wallet, not the server's; amounts per grant; change only to the clan; fee within `min(server, laptop)`; a grant paid once; a replacement must spend the same coins; moves only to a registered newer generation.
- `add_wallet()`: the wallet must include this laptop's key, and the wallet code must match the phone.
- `confirm_address()` and `check_characters()`: 6 after the fixed start and the last 6, with the expected characters never shown.
- `sign()`: unlock, sign only our key's paths, record the payout in the register.
- `connect()`: HTTPS only, no path, no user info.
- Large payouts need the total typed. Unread alarms come before approvals.

**Core changes this proposal needs.** Each one is small, and each gets its own tests:

- `oversight_service.py`, the JSON-lines wrapper;
- the `shown` check;
- merge-on-restore for the register;
- `change_passphrase`;
- `check_words`;
- passphrase-gated `set_limits`;
- report download;
- the DPAPI option.

The console guide keeps working on the same core until Phase C.

### 4.5 Updates

**No auto-update.** An update channel is a way to run new code on the one machine that holds a community's key. A stolen update-signing key, or a hacked download server, would then be one step from signing payouts. Oversight releases are rare, so USB is fine.

1. **The release** is the signed NSIS installer plus a small signed manifest (version, commit, SHA-256), signed with an Afribit release key held offline. The key is Ed25519 (minisign format, which Tauri's tooling already uses).
2. **The app holds the release public key**, built in. **Install an update from a file** checks the installer's hash against the manifest and the manifest's signature, then shows the version and release notes. Only then does it run the installer. This replaces `Get-FileHash` by eye.
3. **The hash still goes by a separate message**, as today, for the first install, when there's no app yet to check it.
4. **No Authenticode certificate** (decided on 6 November 2026). Windows shows "Unknown publisher", so the SHA-256 check in step 3 is what proves the installer is ours. See section 5.

### 4.6 What the Phase 3 external review must cover

1. The Tauri configuration: CSP, capabilities, the command list, the navigation lock, that no other plugin is enabled, and that dev tools are off.
2. The Rust shell: how it starts the core (absolute path, `-I`, no shell), and how it parses messages.
3. `oversight_service.py`: argument checks on every command, the `shown` check, and that no call path signs without `review()`.
4. Key handling: the unchanged file format, DPAPI wrapping and its failure modes, passphrase handling across IPC and in Python memory, and screenshot protection.
5. Updates: release key custody, manifest checking, the installer's signature, and downgrade protection (refuse an older version).
6. Build and supply chain: pinned Cargo.lock, package-lock and Python wheel hashes (`pip --require-hashes`), `cargo audit` and `cargo deny`, and a reproducible build of the kit.
7. The data folder: file permissions, and that nothing secret leaves it (no `server.json` in backups, no words in logs).
8. Everything already in scope for mainnet: `oversight.py`, the server's oversight routes, and the phone signer.

### 4.7 Hardware wallets (Trezor, Ledger) as a signer or oversight key

Asked on 6 November 2026: can a Trezor be a signatory's key or the oversight key? **Not today.** A Ledger can, with work on our side.

**Why.** A clan wallet is a Taproot wallet with two script paths, not a plain multisig:

```
tr(unspendable key, {
  and_v(v:multi_a(1, oversight), multi_a(threshold, signatories)),     normal payouts
  and_v(v:multi_a(recovery_threshold, signatories), older(blocks))      recovery after the wait
})
```

To sign safely, a hardware wallet must understand this whole policy, so it can show where the money goes and recognise the clan's change. That's called Taproot miniscript.

| Device | Taproot `multi_a` with a time lock | Can it be a clan key? |
|---|---|---|
| **Trezor** (Model T, Safe 3, Safe 5) | No. It signs Taproot single-key wallets and older-style multisig only. Miniscript support is in progress, and its own notes say Taproot isn't covered yet | No. Check again when Trezor ships Taproot miniscript |
| **Ledger** (Bitcoin app 2.2.0 or later) | Yes. The app registers "wallet policies" with Taproot miniscript | Yes, once we build it and test it against our exact policy: register the clan's policy on the device, then sign the PSBT over USB |
| **Coldcard**, **Jade**, **BitBox02** | Support differs by model and firmware | Test each one against our exact policy before relying on it |

**What it would take, for a Ledger:**

- **As the oversight key:** the "signer interface" in section 4.1. The desktop app would ask the Ledger to register each clan's wallet once (the device shows the policy, and the person compares the wallet code), then sign each payout on the device. The checks in `review()` still run first, on the laptop. This is Phase D.
- **As a signatory's key:** the phone app would need a Ledger connection (Bluetooth on a Nano X, or USB through the desktop). A bigger change, also later.
- **Keys:** a device makes its own key on account path `87'/0'/0'` (mainnet) or `87'/1'/0'` (test networks), the same paths our phones and laptops use, so Clans accepts it like any other key.

Switching the clan wallet to a plain multisig that Trezor understands would remove the recovery path that protects clans if Clans or the community disappears. That's not worth it.

---

## 5. Packaging and install

- **One installer**, `Afribit-Oversight-Setup-1.0.0.exe`, built by GitHub Actions ([oversight-desktop.yml](../.github/workflows/oversight-desktop.yml)). It's NSIS, per user, needs no admin rights and installs under `%LOCALAPPDATA%`. It installs in the separate `Afribit Oversight` Windows account, as the setup guide says.
- **Works without internet.** It embeds the WebView2 offline installer, which runs only if WebView2 is missing. Windows 11 already has it. The bundled Python and wheels are inside. The Clans address is built into each community's build, as `--url` is today.
- **The data folder doesn't move:** `%LOCALAPPDATA%\AfribitOversight`. The app tells the core to use it, not Tauri's own app-data folder.
- **The command-line tool** stays installed. Administrators run `& "<install dir>\python\python.exe" -I -m clans.oversight <command>`.
- **Python version.** The kit's Python 3.12.10 is the last 3.12 release with Windows downloads, so it gets no more Windows security builds. Move to 3.13 or 3.14 in Phase A, after checking that `bdkpython` and `cryptography` have wheels for it.

**Code signing: decided, none.** The app is private and installed from our GitHub releases or website, not a store, so we don't buy a certificate (decided on 6 November 2026). What that means for the people installing it:

- **SmartScreen** says "Windows protected your PC" and names an unknown publisher. The person clicks **More info**, then **Run anyway**. The setup guide shows this with a screenshot, and says to do it only after the SHA-256 matches.
- **The SHA-256 is the check.** Each release lists it in its notes and in `SHA256SUMS.txt`. The team also sends it by a separate message, as today. On the laptop: `Get-FileHash .\Afribit-Oversight-Setup-<version>.exe`.
- **Smart App Control** (on some new Windows 11 installs) can block unsigned apps outright. On such a laptop it has to be switched off in Windows Security before installing. Check this on the first laptops.
- **Later updates** are checked by the app itself against our release key (section 4.5), which doesn't need a certificate.
- If this changes, the facts checked earlier still hold: an OV certificate lasts at most 460 days and needs a hardware key, and Microsoft's cheaper Artifact Signing serves only organisations in the US, Canada, the EU and the UK.

**Moving an existing laptop off the console:**

1. Install the new app over the old kit, in the same Windows account. The installer removes the old desktop shortcut and the old program folder (`%LOCALAPPDATA%\Programs\Afribit Oversight`). It never touches the data folder.
2. The app finds `oversight-key.json`, `register.json` and `server.json`, and opens on "Welcome to the new Afribit Oversight".
3. It asks for the passphrase once. That proves the key opens, and adds the mainnet public key if it's missing, as `unlock()` does today.
4. It offers "Check my paper backup", then goes to Home.

There's no new key, no new token and nothing for the administrator to do. The same steps work in reverse: reinstalling the console kit still reads the same files.

---

## 6. Plan

Everything below is built and tested on **signet** first. The existing harness, `scripts/e2e_oversight.py` (a private signet in Docker plus a local Clans server), gets a desktop version that drives the app through `tauri-driver` (WebDriver on Windows). The mainnet build is the same app with the network setting changed, and ships only after the Phase 3 review.

| Phase | Work | Size | Done when |
|---|---|---|---|
| **A. Shell and the three most-used screens** | `oversight_service.py` with tests. Tauri shell, capabilities, CSP. A slim core package and newer Python. The oversight UI as its own Vite entry, sharing `styles.css` tokens and `ui.tsx` components. **Home**, **Review and approve** (including the address and wallet code checks) and **Alarms**. Moving existing laptops over. Network band. Unsigned internal build | 3–4 weeks | Both Afribit laptops, moved from the console, approve a signet grant, a refresh and a move end to end. The console still works on the same data |
| **B. Everything else** | First-run setup and restore. Report and CSV. Clans (register, funding address, backup file). This laptop (record backup and restore, check paper, change passphrase, limits, admin lines). Update check from file. DPAPI option. Release manifest signing. Keyboard use, focus states, large text, screen-reader labels | 3–4 weeks | A new laptop is set up from the installer with no internet, and does a signet payout. An update is installed from USB with its signature checked. A second community's laptop runs it too |
| **C. Retire the console** | Remove `oversight_guide.py` and the `.cmd` launcher from the kit. Update [oversight-laptop-setup.md](oversight-laptop-setup.md). Make the desktop e2e the release gate. Hand the app to the Phase 3 reviewer | 1–2 weeks | The setup guide describes only the app. The review has the app in scope |
| *D. Later, if wanted* | A Rust/BDK core inside the shell (no Python). Ledger signing. An "Approve from a file" screen for offline use | — | Decided after the pilot |

**Who builds what.** This follows the usual split (see [frontend-jobs-clan-wallet.md](frontend-jobs-clan-wallet.md)). The screens are built from job documents. The service layer, the Rust shell, packaging, signing and security go on this side.

---

## 7. Questions for the product owner

1. ~~**Code signing.**~~ **Decided:** no certificate. The app is installed from our GitHub or website, and checked by its SHA-256.
2. **Updates by USB only?** The recommendation is yes, with the app checking the signature. Or do you want the app to look for updates on the Clans server later?
3. **Show KES next to sats?** It helps people judge size. The rate would come from the Clans server, so it can only be "about", and the sats figure stays the one that counts. It also needs a small new server route.
4. **Should an unread `unapproved_spend` alarm block approvals for that clan in the core,** not just on screen, until a team member clears it? That changes the checks, so it's your call.
5. **DPAPI on by default?** It's safer if the key file is copied. The catch: an administrator resetting the oversight account's Windows password means restoring from the 12 words.
6. **One big installer or two?** About 160 MB that installs offline on any Windows 10 or 11, or about 35 MB that needs WebView2 already there (every Windows 11 laptop has it).
7. ~~**Languages.**~~ **Decided:** English only.
8. **Grant context on the review screen.** Should the server add the grant's purpose and vote count to the oversight payout view, shown as "from Clans"?
9. **Rust ownership.** Is someone happy to own a roughly 300-line Rust shell? If not, use the pywebview fallback.
