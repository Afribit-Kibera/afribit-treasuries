# Afribit Treasuries

Bitcoin treasuries for savings groups (chamas, clans, SACCOs) that nobody can run off with.

Members save together, vote on grants, and repay into the group. The money sits in a Bitcoin multisig wallet. Payouts need signatures from the group's own signatories, made on their phones, plus one approval from the group's community, made on an oversight laptop. No single person, and not the server, can move the money alone.

Built by [Afribit Africa](https://afribit.africa). Licensed under the [GNU AGPL v3](LICENSE).

> **Status: not yet externally security reviewed.** Mainnet is the default network and has been tested with real sats ([docs/mainnet.md](docs/mainnet.md)), but the code hasn't had an independent review yet. Use small amounts. Try it on signet first.

## How custody works

Every clan wallet is a Taproot multisig with two ways to spend:

| Path | Who signs | When |
|---|---|---|
| Normal | A majority of the clan's signatories (for example 2 of 3, 3 of 5 or 4 of 7) **and** one of its community's oversight keys | Any time |
| Recovery | A majority of the signatories, alone | After a coin has sat unspent for the recovery period (about 6 months by default) |

What this means:

- **The community can't take the money.** An oversight key can only add the last signature to a payout the clan has already signed.
- **A thief who steals the treasurer's phone can't take it either.** One signatory can't sign alone.
- **The server can't take it.** It holds public keys only. Phones and oversight laptops rebuild the wallet themselves, check every payout before signing, and never trust the server about money.
- **The clan is never locked in.** If the community or the server disappears, the signatories recover the money on the recovery path with their backup words and the public wallet backup ([docs/clan-wallet-recovery.md](docs/clan-wallet-recovery.md)). Coins are refreshed before the recovery period runs out, so it only opens if the normal path stops working.

A **community** is the group that runs oversight for its clans, such as an NGO, a cooperative or a group of elders. Each community has 1 to 3 oversight laptops and sees only its own clans ([docs/communities.md](docs/communities.md)).

## What's here

| Path | What it is |
|---|---|
| `backend/` | The server (Python, FastAPI, PostgreSQL): accounts with passkeys, clans, votes, grants and repayments, clan wallets, and the chain watcher |
| `frontend/` | The phone app (React PWA). Signatories' keys stay on the phone, encrypted |
| `oversight-desktop/` | **Afribit Oversight**, the Windows app for oversight laptops (Tauri). It checks and approves payouts ([docs/oversight-desktop-app.md](docs/oversight-desktop-app.md)) |
| `backend/src/clans/oversight*.py` | The oversight core, and a guided console version of the same app |
| `backend/src/clans/recover.py` | Recovers a clan's money on the recovery path, without the server |
| `docs/` | Design, API contracts, recovery and setup guides |

The code also contains an older Lightning account mode, in which the operator's Lightning node holds the money. That mode is **custodial**: the operator can spend it, and votes are enforced only by the app. It's off unless an operator configures a payment provider.

## Try it locally

You need Python 3.12 or newer and Node.js 24. From the repository root in PowerShell:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r backend/requirements-dev.lock
.venv/Scripts/python.exe -m pip install --no-deps -e backend
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run build
.venv/Scripts/python.exe scripts/run_live_preview.py
```

Open http://localhost:8410/. The preview uses its own SQLite database under `.local/` and starts empty.

To try clan wallets end to end with a simulated Bitcoin network, see [docs/wallet-frontend-checks.md](docs/wallet-frontend-checks.md).

## Run it for a community

1. **Oversight laptops first.** Set up 1 to 3 laptops with Afribit Oversight ([docs/oversight-laptop-setup.md](docs/oversight-laptop-setup.md)) and note their public keys.
2. **The server.** PostgreSQL, HTTPS, and the settings in [backend/.env.example](backend/.env.example). Set `CLANS_CLAN_WALLETS_ENABLED=true` and the oversight keys. The network is Bitcoin mainnet unless you set `CLANS_CLAN_WALLET_NETWORK=signet`. The server refuses to start if a key doesn't match the network.
3. **Block explorers.** The chain watcher uses mempool.space and blockstream.info unless you list others in `CLANS_CLAN_WALLET_ESPLORA_URL`. Put your own Esplora node first (electrs, or the mempool app on an Umbrel): public explorers rate-limit ([docs/mainnet.md](docs/mainnet.md#block-explorers)).
4. **The oversight app.** Build it with your server's address: set `OVERSIGHT_CLANS_URL` when building, or run the `oversight-desktop` workflow with `clans_url`.

Keep provider credentials, backup words, wallet backups and database dumps out of Git.

## Checks

```powershell
.venv/Scripts/python.exe -m pytest -q backend/tests
.venv/Scripts/python.exe -m ruff check backend
npm.cmd --prefix frontend run build
```

Without PostgreSQL settings, the database permission and concurrency tests are skipped. A SQLite result is not a production database result.

## Documents

- [Security review guide](docs/security-review.md)
- [Clan wallet API](docs/clan-wallet-api.md) and [the plan behind it](docs/multisig-treasury-plan-2026-11-04.md)
- [Recovering a clan's money](docs/clan-wallet-recovery.md)
- [Mainnet](docs/mainnet.md)
- [Communities](docs/communities.md)
- [The oversight desktop app](docs/oversight-desktop-app.md) and [setting up an oversight laptop](docs/oversight-laptop-setup.md)
- [User journeys](docs/user-journeys.md)
- [Reports](docs/reports.md)

## Security

Please report vulnerabilities privately. See [SECURITY.md](SECURITY.md).

## Licence

Copyright © 2026 Afribit Africa.

This program is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License, version 3, as published by the Free Software Foundation. It comes with no warranty. If you run a modified version for other people over a network, you must offer them its source code. See [LICENSE](LICENSE).
