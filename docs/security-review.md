# Security review guide

For the external reviewer. This is the review that comes before production (Phase 3 in the
[plan](multisig-treasury-plan-2026-11-04.md#phases-and-gates)). Mainnet code paths exist and were
tried with small real amounts, but the project isn't production-ready until this review's
findings are fixed.

## What's in scope

The non-custodial clan wallet: everything that can move, hold or misreport the money.

| Area | Where | The question |
|---|---|---|
| Wallet policy | `backend/src/clans/clan_wallet.py`, `frontend/src/vault/policy.ts` | Do the server and phones build the same Taproot policy, and can any key set spend outside it? |
| Phone signer | `frontend/src/vault/` | Can a malicious server make a phone sign something other than the payout shown, or leak its backup words? |
| Oversight core | `backend/src/clans/oversight.py`, `oversight_service.py`, `oversight_guide.py` | Can a malicious server get an oversight signature on a payout the clan didn't sign, or to an unexpected address? |
| Oversight desktop app | `oversight-desktop/src-tauri/` | Can the window run anything other than the oversight core's known commands? |
| Server API | `backend/src/clans/wallet_api.py`, `wallet_money_api.py`, `wallet_payments.py`, `live_app.py` | Authentication (passkeys), membership checks, votes, the signature upload routes |
| Chain watcher | `backend/src/clans/chain_watcher.py`, `explorers.py` | Crediting deposits, building and broadcasting payouts, reorgs, refreshes, moves between wallets |
| Recovery | `backend/src/clans/recover.py`, [clan-wallet-recovery.md](clan-wallet-recovery.md) | Can signatories always recover the money without the server or the community? |
| Database roles | `backend/src/clans/database_roles.py` | The web app and the chain watcher each get only the rights they need |

Out of scope unless you want it: the older Lightning account mode (`treasury_provider.py`,
`treasury_worker.py`, `payments.py`). It's custodial by design, and it's off unless an operator
configures a BTCPay store.

## How to run it

Python 3.12 or newer and Node.js 24, from the repository root in PowerShell:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r backend/requirements-dev.lock
.venv/Scripts/python.exe -m pip install --no-deps -e backend
npm.cmd --prefix frontend ci
.venv/Scripts/python.exe -m pytest -q backend/tests
.venv/Scripts/python.exe -m ruff check backend/src backend/tests
npm.cmd --prefix frontend run build
npm.cmd --prefix frontend run check:sweeps
```

The tests use SQLite. Set the PostgreSQL settings in `backend/.env.example` to run the
database role and concurrency tests too. To click through the app against a simulated Bitcoin
network, see [wallet-frontend-checks.md](wallet-frontend-checks.md). The desktop app is built by
`.github/workflows/oversight-desktop.yml`.

Main libraries: bdkpython 3.1.1 (server, oversight, recovery), @scure/btc-signer 2.4.1 with
@scure/bip32 and @scure/bip39 2.4.0 (phones), Tauri 2.12 (desktop), FastAPI 0.162, SQLAlchemy 2.1,
webauthn 3.0.1.

## Known risks we've accepted

Tell us if you think any of these shouldn't be accepted.

- **The server serves the phone app's code.** A compromised server could ship code that copies
  every signatory's key. It still can't spend: payouts also need an oversight laptop, which
  never runs the web app.
- **The oversight key is a software key** in a separate Windows account, not a hardware device.
  Malware there, while the passphrase is typed, could sign. It would still need the clan's
  majority.
- **The phone PIN fallback** (phones without passkey PRF) stops casual access, not someone who
  copies the phone's storage and tries every PIN. One stolen key can't spend alone.
- **Key registration doesn't ask for the passkey again.** A stolen session could swap that
  signatory's key before the wallet is active. The phone checks its own key is in the wallet
  before confirming, and signatories compare the wallet code.
- **The oversight signature route needs no session.** It's rate-limited and stores only valid
  signatures by that clan's oversight keys on the exact payout.
- **Block explorers see the clans' addresses** unless the operator runs their own
  ([mainnet.md](mainnet.md#block-explorers)).
- **The desktop installer isn't Authenticode-signed.** Its SHA-256 is sent separately and
  checked before installing.

## Not done yet

- This review, and fixing what it finds.
- The signet pilot with a real group (Phase 2): a full cycle by real members, a recovery
  without the app or the community, a lost phone and a refresh. The recovery rehearsal is
  planned for December 2026.

## Reporting

Use private vulnerability reporting ([SECURITY.md](../SECURITY.md)).
