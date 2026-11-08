# Afribit Treasuries phone app

The members' app, a React PWA. Members create and join clans, vote on grants and repay. Signatories make their wallet key from 12 backup words, keep it encrypted on the phone, and sign payouts. The entry point is `src/LiveApp.tsx`.

## The money code

The phone never trusts the server about money. These files do the checking:

| File | Does |
|---|---|
| `src/vault/keys.ts` | Makes a signatory's key from their backup words, for the wallet's network |
| `src/vault/policy.ts` | Rebuilds the clan wallet from its public policy and computes the wallet code that signatories compare |
| `src/vault/sign.ts` | Reviews a payout (amounts, addresses, fee, change) and signs it only if the review passes |
| `src/vault/store.ts` | Keeps the backup words encrypted on the phone, unlocked with a passkey or PIN |
| `src/wallet-backup.ts` | The public wallet backup that signatories need for the recovery path |

## Run locally

From the repository root, install the backend and build this app:

```powershell
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run build
.venv/Scripts/python.exe scripts/run_live_preview.py
```

Open http://localhost:8410/. For Vite development, run `npm.cmd run dev` in this folder. Its `/api` proxy targets the local backend.

To try the clan wallet screens against a simulated Bitcoin network, see [docs/wallet-frontend-checks.md](../docs/wallet-frontend-checks.md).

## Checks

```powershell
npm.cmd run build
npm.cmd run check:sweeps
```

Design assets and font licences are listed in [ASSETS.md](ASSETS.md). Run `node scripts/optimize-assets.mjs` in this folder to rebuild the WebP images and font copies.
