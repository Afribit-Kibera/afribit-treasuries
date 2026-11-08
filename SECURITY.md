# Security

Afribit Treasuries holds real bitcoin for savings groups. Please report problems privately so they can be fixed before anyone loses money.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting: open the repository's **Security** tab and choose **Report a vulnerability**. Don't open a public issue for a security problem.

Please include what you found, how to reproduce it, and what an attacker could do with it. We'll reply as soon as we can.

## Status

The code hasn't had an independent security review yet. Until it has, use small amounts. Reviewers: start with [docs/security-review.md](docs/security-review.md).

## What to look at

These matter most, because each one guards the money:

- **Phones and oversight laptops check every payout themselves.** They rebuild the wallet from its public policy and refuse to sign anything they can't verify (`frontend/src/vault/`, `backend/src/clans/oversight.py`).
- **The server never holds a private key.** A compromised server shouldn't be able to move money, swap a wallet's keys, or trick a signer into signing a different payout.
- **The recovery path.** Signatories must be able to recover the money without the server or the community (`backend/src/clans/recover.py`).
- **The oversight desktop app.** Its window may only call the oversight core, and only with the commands it knows (`oversight-desktop/src-tauri/`).
