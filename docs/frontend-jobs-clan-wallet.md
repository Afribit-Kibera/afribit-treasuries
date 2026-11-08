# Frontend jobs: clan wallet screens

**For:** whoever builds the phone screens.
**From:** the backend and security side, working in parallel on `feat/multisig-treasury`.
**Date:** 4 November 2026.

## Context in one paragraph

Clans is moving clan money out of a server-run Lightning node and into one Bitcoin multisig wallet per clan. Signatories hold their keys on their phones, inside this PWA. A payout needs Afribit's oversight key plus a majority of the clan's signatories; the server only holds public keys. Read the [plan](multisig-treasury-plan-2026-11-04.md) sections "How a clan wallet works" and "Main flows". Read the [API contract](clan-wallet-api.md) completely. Your job is the screens. The wallet maths already exists in `frontend/src/vault/` and is tested against the backend.

## Where to work

- Branch from `feat/multisig-treasury`. Name it `feat/clan-wallet-screens`, or one branch per job: `feat/clan-wallet-screens-f1` and so on.
- Open a PR into `feat/multisig-treasury` per job or per pair of jobs. Don't merge into `main`.
- Don't push to `feat/multisig-treasury` directly.

## Rules

### Design

- Keep the existing design. Reuse the existing tokens, fonts and components: `Sheet`, `Busy`, `Avatar` and the money helpers in `src/ui.tsx`, plus `CopyButton`, `LocalMoney` and the `live.css` / `styles.css` classes.
- Follow the patterns in `MoneyFlows.tsx` (payment approval) and `ActivityScreen.tsx`.
- No new visual language, colour tokens or icon set. Use `@phosphor-icons/react`, which is already installed.
- Plain language for members with little Bitcoin experience. Say "signing key", "backup words", "wallet code" and "network fee". Never say PSBT, descriptor, xpub or UTXO on screen.
- Show money in sats with the local-currency estimate the app already shows (KES). Use the existing helpers; don't add new rate fetching.
- Every screen works at 320, 390, 430, 768 and 1366 px wide, in light and dark themes, with no horizontal scroll.

### Security (hard rules)

1. **Never send, log, store in plaintext, or put in analytics:** backup words, private keys or PIN. Hold the words in memory only for the moment they're needed, then drop references.
2. **Never display the server's `wallet_code` as the thing to compare.** Compute the code on the phone with `walletCode()`, and show and submit that. You may show "Server says: …" in a collapsed diagnostics row only.
3. **Never offer "Sign" unless `reviewPayout()` succeeded on this phone** for exactly that PSBT and expectation. If it throws, show a stop state with the error message and no way to sign.
4. Before confirming a wallet, check that the phone's own key (from its vault) is in `policy.signers`. If it isn't, show a stop state.
5. Before showing a deposit or repayment address, check it with `clanOutput(policy, "external", index).address`. If it doesn't match, show a stop state.
6. Don't edit `src/vault/policy.ts`, `src/vault/sign.ts` or `src/vault/keys.ts`. They're cross-checked against the backend by `backend/tests/test_clan_wallet_interop.py`. If you need a change there, write it up in your PR description instead.
7. Don't implement any encryption or key storage. Use the `vault/store.ts` interface below.
8. No new dependencies without asking in the PR. QR display uses `qrcode`, which is already installed. If you need QR scanning, propose a library in the PR. Don't add one.

### Feature gating

Show nothing new unless `GET /api/clans/{id}/wallet` returns `enabled: true`. Clans without an active wallet keep today's Lightning flows unchanged.

### Checks before every PR

- `npm run build`, which runs `tsc -b` and then `vite build`, passes in `frontend/`.
- If the backend environment exists, run `backend/tests/test_clan_wallet_interop.py`. It must still pass.
- Visual QA:
  - Screenshots at 390×844 in both themes into `output/playwright/clan-wallet-<screen>-<theme>.png`.
  - A note on the widths you checked.
  - Fix P0–P2 issues before opening the PR.
- Every API failure has a loading, error and retry state.

## Shared pieces you can rely on

### Wallet maths (exists)

```ts
import { createBackupWords, signerFromWords } from "./vault/keys";
// createBackupWords(): string                 12 words
// signerFromWords(words): { info: SignerKeyInfo; account }
import { clanOutput, keyExpression, parseKey, walletCode, type ClanPolicy } from "./vault/policy";
import { reviewPayout, signPayout, amountsReceived, type PayoutExpectation } from "./vault/sign";
```

Map the API's `policy` to `ClanPolicy` as the API contract describes:

```ts
{
  network,
  oversight: oversight.map(parseKey), // 1–3 Afribit keys, any one approves; keep the order
  signers: signers.map(parseKey),
  recoveryThreshold: recovery_threshold,
  recoveryBlocks: recovery_blocks,
}
```

All of these functions throw `ClanWalletError` with a member-readable message.

### Key store (built by us; code against this interface)

`frontend/src/vault/store.ts` is built and exports:

```ts
export type Unlock = { kind: "passkey" } | { kind: "pin"; pin: string };
export type Protection = "passkey" | "pin";
/** Which protections this device supports. Passkey needs WebAuthn PRF support. */
export function vaultSupport(): Promise<{ passkey: boolean; pin: true }>;
export function vaultProtection(clanId: string): Promise<Protection | null>; // null = no key on this phone
export function saveVault(clanId: string, words: string, unlock: Unlock): Promise<void>;
/** Returns the backup words. Throws VaultLockedError on a wrong PIN or cancelled passkey. */
export function openVault(clanId: string, unlock: Unlock): Promise<string>;
export function forgetVault(clanId: string): Promise<void>;
export class VaultLockedError extends Error {}
```

The real store is now on the branch, and `vault-access.ts` picks it up automatically. Keep `store-preview.ts` for development only; the production build must not import it.

Notes for the screens:

- PINs are 6 to 12 digits.
- Every `VaultLockedError` message is written for members, so show it as it is. It covers a wrong PIN, a cancelled passkey and "Too many wrong PINs. Try again in N minutes" after five wrong tries.
- Passkey protection uses the member's existing Clans passkey. If `saveVault` with a passkey throws "This passkey can't protect your signing key", offer the PIN instead.
- `saveVault` replaces any key already saved on the phone for that clan. Use it for F7 restore too.

### Fixtures

Create `src/wallet-fixtures.ts`, used only in development, with:

- one wallet view per `status`;
- one payout draft that passes review;
- one tampered draft that fails review.

Build valid PSBT fixtures by asking in the PR, or generate them from the interop harness: `frontend/scripts/clan-wallet-interop.ts` shows how. Never put real mainnet data in fixtures.

## Jobs

Do them in order. Every route F1–F8 uses is now implemented; only the Lightning till is still planned. F8 moves F4–F6 from fixtures to the real routes.

### F0. Wallet API client and types

- In `src/wallet-api.ts`, add typed functions for every route in the API contract, implemented and planned, using the existing `api()` from `live-api.ts`.
- Add a `toClanPolicy(view.policy)` helper.
- Add `src/wallet-fixtures.ts` as above.

**Done when** the types match the contract exactly and the build passes.

### F1. Set up your signing key (signatories)

Entry point: a card on the clan screen when `status` is `not_started` or `collecting_keys` and `me.is_signer` is true and `me.key` is null.

Steps (one per screen, in a `Sheet` or full screen to match existing flows):

1. **Why:**
   - "You'll hold one of the clan's signing keys on this phone."
   - Say what this means: payouts need your approval and Afribit's.
   - Say what happens if you lose the phone: your backup words restore the key.
2. **Backup words:** show the 12 words from `createBackupWords()`, numbered, large.
   - Warn: write them on paper, no screenshots, never share them, Afribit will never ask.
   - These are **not** the account recovery words the app already has. Say so clearly.
3. **Check:** ask for 3 randomly chosen words by position. Wrong answers go back to step 2.
4. **Protect:** offer passkey if `vaultSupport().passkey`, otherwise a PIN of at least 6 digits, entered twice. Call `saveVault()`.
5. **Register:** `POST /wallet/keys` with `keyExpression(signerFromWords(words).info)`.
   - On success, show the waiting list.
   - On `409` "already registered", explain and offer to start again.

**Waiting list:** every signatory's name with "key added" or "waiting", plus a refresh. Show it to all members, read-only for non-signatories.

**Done when:**
- a signatory can go from nothing to a registered key;
- the words appear only on step 2 and in no request;
- refreshing mid-flow never registers a key the phone didn't save first.

### F2. Compare the wallet code (signatories)

Shown when `status === "confirming"` and `me.confirmed` is false.

1. Open the vault, using passkey or PIN. Check that `keyExpression(signerFromWords(words).info)` equals `me.key` and is in `policy.signers`. Otherwise show a stop state.
2. Compute `walletCode(toClanPolicy(policy))` on the phone. Show it very large in two groups of four (`8yq3 zv5k`), with: "Compare this code with every other signatory, in person or on a call. All codes must be the same."
3. Two buttons:
   - "All codes match" sends `POST /wallet/confirm` with the phone's code.
   - "Codes are different" shows a stop state telling them not to use the wallet and to contact Afribit, and doesn't confirm.
4. A `409` mismatch response shows the same stop state.
5. When `status` becomes `active`, show "Clan wallet ready" with the rule in plain words: "Payouts need N of M signatories and one Afribit approver. If Afribit can't sign for 6 months, N signatories can recover the money themselves."

**Done when** confirmation uses only the phone-computed code, and the mismatch and missing-key stop states are reachable with fixtures.

### F3. Clan wallet card and status

On the clan screen (`ClanScreen.tsx`), add a compact card for every member:

- the wallet status;
- the setup progress ("2 of 3 keys added", "1 of 3 confirmed");
- the network badge "Test network" while `network` isn't mainnet;
- when active: the payout rule in one line, and the recovery wait in days.

Don't change the existing balance and treasury figures yet. Wallet balances arrive with the planned routes.

**Done when** it's correct for each `status` fixture and the existing clan screen layout is preserved.

### F4. Review and sign a payout (signatories), against fixtures

The entry point is the existing grant payment section in `MoneyFlows.tsx`. When the clan wallet is active, a payout draft replaces the passkey "Approve this payment" flow. Keep that flow for clans without a wallet.

1. Show, from the draft:
   - who gets paid;
   - their address, shortened, with expand and copy;
   - the approved amount;
   - the network fee in sats and KES, and who pays it;
   - what the beneficiary receives;
   - signatures so far ("1 of 2 signatories, then Afribit").
2. Run `reviewPayout(psbt, policy, expectation)` on the phone.
   - On success, show a "Checked on this phone" line.
   - On a throw, show a stop state with the message and **no** sign button.
3. "Sign payout" opens the vault, calls `signPayout()`, then `POST …/signature` with the signed copy, then drops the words.
4. Status timeline: waiting for signatories → waiting for Afribit → sent → confirmed (with confirmations count). A `replaced` draft links to the version that went out instead (see F8).

**Done when:**
- the passing fixture can be signed;
- the tampered fixture can't, and shows why;
- the fee and received amounts match `amountsReceived()`.

### F5. Beneficiary payout address, against fixtures

This replaces "paste a Lightning invoice" for clans with an active wallet.

1. Explain: "Paste a Bitcoin address from your wallet. Phoenix, Blink, Breez and most wallets have one under Receive → Bitcoin address."
2. Validate the address on the phone. It must decode on the test network: use `Address(TEST_NETWORK).decode` from `@scure/btc-signer`, wrapped in a try/catch helper in `wallet-api.ts`.
3. Show the preview: approved amount, estimated network fee and "You'll receive about X". Note that the fee comes out of the grant, and that some Lightning wallets charge a small fee to bring on-chain money in.
4. Confirm sends `POST …/payout-address`.

**Done when** invalid and mainnet addresses are refused on the phone with a clear message, and the received-amount maths is shown.

### F6. Contribute and repay to the clan wallet, against fixtures

1. For repayments and contributions, fetch an address (planned route), check it with `clanOutput()`, then show:
   - a QR of `bitcoin:<address>?amount=<btc>`;
   - the address with copy;
   - the amount in sats and KES.
2. Explain that most Lightning wallets can send to a Bitcoin address, and that the member pays that send fee.
3. Advise against on-chain repayments under 5,000 sats. Point to the Lightning till when the API says it's available.
4. Show "Waiting for the network" (unconfirmed), then "Received" (confirmed), using the existing deposit status patterns.

**Done when** an address that fails the phone's check never shows a QR.

### F7. Restore a signing key on a new phone

From the wallet card: "I have a new phone".

1. Enter the 12 backup words (word-by-word inputs with BIP-39 autocomplete; the word list comes from `@scure/bip39`).
2. Check that `keyExpression(signerFromWords(words).info)` equals `me.key`. If it doesn't, say "These words are for a different key" and don't save.
3. Protect with a passkey or PIN via `saveVault()`.

**Done when** the right words restore the key, the wrong words are refused, and nothing is sent to the server.

### F8. Use the real payout, address and receipt routes

The backend for F4–F6 is in. The [API contract](clan-wallet-api.md) lists every response and error.

1. **Types** in `src/wallet-api.ts`:
   - Payout `status` gains `broadcasting`: every signature is in and the server sends it within about 30 seconds. Show it as "Sending". The full list is `awaiting_signatures`, `awaiting_oversight`, `broadcasting`, `broadcast`, `confirmed`, `expired`, `replaced`.
   - The payout view gains `clan_id`, `replaces` and `replaced_by`.
   - Add the oversight upload route only if you need its type. No screen uses it.
2. **F4:**
   - The draft's `psbt` already holds the signatures collected so far. Review and sign it as it is.
   - `expired` means the beneficiary changed the address, and `replaced_by` names the new draft. `replaced` means another version went out or confirmed instead. Link to the other draft in both cases.
   - A payout stuck on the network for hours can get a new draft with a higher fee. It has `replaces` set to the sent payout, which stays `broadcast` until one of them goes through. On the sent payout, say "Taking longer than usual. A version with a higher fee needs your signature" and link to the new draft. Find it with `GET …/wallet/payouts?grant_id=…&status=awaiting_signatures`.
   - A `409` after signing (for example "A signature doesn't match this payment. Sign it again.") shows its message. The draft stays unsigned.
3. **F5:**
   - Call `GET …/payout-quote?address=` for the preview, then `POST …/payout-address` on confirm.
   - A `503` means the server can't see the Bitcoin network right now. Say so and offer to try again.
   - A `409` "The clan needs enough confirmed money for this grant." means the clan must wait for deposits to confirm.
   - Giving a different address later is allowed until the payout goes out. Signatories then sign a new draft.
4. **F6:**
   - `GET …/wallet/address?purpose=contribution` for contributions.
   - `purpose=repayment&grant_id=…` for repayments, only while the grant is `in_recovery`.
   - `purpose=grant_funding`, with no `grant_id`, for the clan's main funding address.
   - Track payments with `GET …/wallet/receipts?address=`, polling every 30 seconds while one is `pending`.
5. Keep the fixtures for development, and update them to these shapes.

**Done when** F4–F6 run against a local backend with `CLANS_CLAN_WALLETS_ENABLED=true`, and every status and error above has a message.

### F9. Save the wallet backup file (signatories)

Why: with this file and their 12 words, the signatories can recover the clan's money without Clans or Afribit, once the recovery wait has passed. Without it, the words alone aren't enough. The format is in the [API contract](clan-wallet-api.md) under "Wallet backup file".

1. On the wallet card, once the wallet is `active` and this phone has compared the wallet code, add "Save wallet backup".
2. Build the file on the phone from the policy that was checked (the same one `walletCode()` ran on), never from a server response:
   - `descriptors.external` and `descriptors.internal` are `descriptor(policy, keychain) + "#" + descriptorChecksum(descriptor(policy, keychain))`;
   - `wallet_code` is `walletCode(policy)`;
   - `threshold` is `threshold(policy)`;
   - `generation` and `clan_id` come from the wallet view.
3. Download it as `<clan name>-wallet-backup.json`. Say:
   - "This file holds no secrets. Keep it with your backup words, and keep a second copy somewhere else."
   - "Together with enough signatories' words, it can recover the clan's money if Clans or Afribit is ever unavailable."
4. Remember on the phone that it was saved, and show a reminder on the wallet card until it is.
5. Add a fixture test: the file built for `wallet-fixtures.ts` passes `python -m clans.recover check` (the backend tests can run it if you write the file to `.local/`).

**Done when** a signatory can save the file in both themes on a phone-width screen, the file matches the format exactly, and the reminder clears after saving.

### F10. Move to a new clan wallet, and sign moves and refreshes

Why: a wallet's keys can't change once it's active. When a phone is lost or stolen, or a signatory or Afribit key changes, the clan sets up a new wallet and the old wallet's money is moved into it. The backend is in. The [API contract](clan-wallet-api.md) explains it under "New wallet generation" and "Refreshes and moves".

1. **Keep a wallet check per generation** (`src/wallet-trust.ts`):
   - Store each checked record under clan **and** generation, so a new check doesn't replace the old one. Read existing `v1` records as the generation they name.
   - `checkedWallet()` takes the generation it should return, and refuses a record whose policy differs from the view of that generation. For an `earlier` generation there's no policy in the view: use the saved record, and check that its code equals the `earlier` entry's `wallet_code`.
   - Never delete an old generation's record.
2. **Start a new wallet** (signatories, on the wallet card): "Start a new clan wallet", with a reason picker: lost key, stolen phone, signatory change, Afribit key change, other. Call `POST …/wallet/next`. Say: "Your current wallet keeps working. Every signatory sets up and compares the new wallet. Then the money moves across, signed like a payout."
3. **Set up `next`.** When the view has `next`, show it as a second card, "New clan wallet (generation N)":
   - It shows who started it, the reason, and each signatory's progress, as at first setup.
   - Register a key with the same F1 flow. If this phone already has the clan key, offer "Use my current key" first, and say: "Keep your current key if you still have it. A new key is only needed if yours was lost." A new key only goes in the vault once the move has gone out, or if this phone has no key.
   - Compare the code with the F2 flow, against `next.policy`, and save the check for that generation.
   - "Stop setting up" calls `POST …/wallet/next/cancel` after a confirmation.
4. **After the switch.** The top level of the view becomes the new wallet, and the old one shows under `earlier`. Show "Old wallet (generation N): X sats still to move" until `balance_sats` is `0`, and remind each signatory to save the **new** backup file (F9), with "Keep your old backup too."
5. **Sign refreshes and moves** in F4. For `kind` `refresh` or `move`:
   - There are no beneficiaries. Show "Move to the clan's new wallet (generation N)" or "Refresh: the clan's coins go back to its own wallet, so the 6-month recovery wait starts again".
   - Use `reviewSweep()` and `signSweep()` from `vault/sign.ts`, never `reviewPayout()`. The source policy is the saved check for `payout.generation`. The destination policy is the saved check for `payout.destination.generation`. Use `payout.destination.index`, and never `payout.destination.address`.
   - If this phone has no check for either generation, the payout isn't signable: "Compare the new wallet's code on this phone first."
   - If the vault key isn't in the source wallet (a signatory who got a new key), say "Your key changed, so the other signatories sign this one." No sign button.
   - Show the amount and the fee from the review result, not from the server.
6. **Payouts from an old wallet.** A grant draft whose `generation` is older than the active wallet's is still signable: review it with that generation's saved check.
7. Add fixtures: a wallet view with `next` collecting keys, one with `earlier`, a move payout and a refresh payout. Check them with `reviewSweep()` in the fixture test.

**Done when:**

- a clan can start, set up, compare and cancel a new wallet;
- a phone keeps the old generation's check after the switch, and can review and sign the move with it;
- a move to an address the phone didn't derive, or a refresh with a changed index, is refused;
- every error in the contract's "New wallet generation" table has a message;
- it works in both themes at phone width.

### F11. Show wallet alarms to members

Why: when something goes wrong with a clan wallet (money leaving without an approved payout, a phone computing a different wallet code, a payment disappearing from the blockchain), every member should hear about it in the app, not only Afribit. The backend is in. The [API contract](clan-wallet-api.md#alarms) explains it under "Alarms".

1. **Banner on the wallet card** (F3): when the wallet view's `alarms_recent` is above `0`, show a warning banner: "N wallet alarm(s) in the last 30 days." Tapping it opens the list. Use the existing warning style, not a new colour.
2. **Alarm list**: call `GET /api/clans/{clan_id}/wallet/alarms`. For each alarm show `message`, the date, and "wallet generation N" when the clan has more than one generation. Show the newest first. With no alarms, say "No alarms. Clans tells every member here if something unusual happens in the clan wallet."
3. **Stop before signing**: on the F4 signing screen, if the list has an `unapproved_spend` alarm from the last 30 days for the generation being signed, show it above the sign button: "Money left this wallet without an approved payout. Check with Afribit before you sign." The signatory can still sign after reading it.
4. Show unknown kinds with their `message`. Don't show `detail` or `reference` to members, except `phone_code` for `wallet_code_mismatch`, so signatories can compare it with their own.
5. Add fixtures: a wallet view with `alarms_recent: 2`, and an alarm list with `unapproved_spend` and `wallet_code_mismatch`.

**Done when:**

- the banner shows only when `alarms_recent` is above `0`, for signatories and plain members;
- the list shows every kind in the contract's table with its message;
- the signing screen warns about a recent `unapproved_spend` on that wallet;
- it works in both themes at phone width.

### Note for F10 and F11: Lightning switches don't apply to clan wallets

On the base branch, `LiveApp.tsx` and `WalletGrantMoney.tsx` no longer use `session.capabilities.receiving` or `payouts` for clan wallet actions. Those switches are about Lightning only. The pilot runs with Lightning off, and "Add money", "Repay" and signing must still work there. When an active clan wallet exists, use `canReceive` (in `LiveApp.tsx`) and leave signing on. Keep this when you merge the base branch into your work.

### F12. Activity titles and an activity detail page

**Status: done.** The list is in `ActivityScreen.tsx` and the detail page in `ActivityDetail.tsx`. To try it without a backend, open `/__wallet_preview` in development and choose "Show test activity".

The Activity list showed many rows as "Clan updated", because `eventLabels` in `LiveApp.tsx` doesn't know the wallet events. The server now titles and explains every event. Contract: [clan-wallet-api.md, Activity](clan-wallet-api.md#activity). Read [user-journeys.md](user-journeys.md), Journey 6.

Build:

1. **Titles from the server.** In the Activity list, show `item.title`. Keep `eventLabels` only as a fallback for an older server, and drop "Clan updated" as a label.
2. **Tap a row to open its detail page.** Use a `Sheet` on phones, as other details do. Load `GET /api/clans/{id}/activity/{event_id}` and show:
   - the title, who did it and when;
   - `summary` as the main text;
   - `details` as label and value rows, in the style of the payout review rows;
   - the related records from `links`, as buttons: "Open the grant" (`grant_id`, opens the existing grant sheet), "Open the payment" (`payout_id`, opens the existing payout view), and "View on a block explorer" (`txid`). Build the explorer link from the wallet's network: `https://mempool.space/tx/<txid>` for `bitcoin`, and `https://mempool.space/signet/tx/<txid>` or `/testnet4/` for the test networks. Open it in a new tab.
3. **Category icons.** Use one existing Phosphor icon per `category` (`clan`, `members`, `grants`, `money`, `wallet`, `security`, `account`) instead of one icon per event type. Show `security` rows in the existing warning colour.
4. **Loading, error and 404 states**, following `ActivityScreen.tsx`. A 404 says "This activity isn't in your clan."

Don't show raw `event` names, ids or the `data` object on screen.

Done when:

- no row in the trial clan's history says "Clan updated";
- each row opens its detail page, and its links open the grant, the payment and the explorer;
- it works in both themes at 320, 390 and 768 px.

## Not in scope for you

- Encryption and the key store: we build `vault/store.ts`.
- Backend routes, the database, the chain watcher and the oversight signing tool.
- The Lightning till's backend.
- Text about custody on the public product page. Afribit approves that text after the external review.

## Questions

Write them in the PR description, under "Questions for backend". If a question blocks you, build the screen against a fixture and note what you assumed.
