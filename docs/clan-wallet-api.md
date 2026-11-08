# Clan wallet API contract

**Status:** Setup, address, payout-address, receipt and payout routes are implemented on `feat/multisig-treasury`, as are new wallet generations (after a lost phone or a roster change) and the moves and refreshes that follow them. The Lightning till is still planned. The answers to the questions in PRs #7–#10 are included below. Shapes may still change; this file is updated when they do.
**Plan:** [multisig-treasury-plan-2026-11-04.md](multisig-treasury-plan-2026-11-04.md)
**Machine-readable:** implemented routes are in [api/clans-live-openapi.json](api/clans-live-openapi.json).

All routes sit under the live app's `/api` prefix and use the existing session cookie, CSRF header and `{"detail": "..."}` error format (`frontend/src/live-api.ts` `api()` already handles these).

## Ground rule for every client

**The phone never trusts this API about money.** The server can be compromised. So:

- The phone rebuilds the wallet itself from `policy` with `frontend/src/vault/policy.ts`, and computes its own wallet code. It confirms with **its own** code, never the server's `wallet_code` field.
- The phone checks that its own key is among `policy.signers` before confirming.
- The phone runs `reviewPayout()` (grants) or `reviewSweep()` (refreshes and moves) from `frontend/src/vault/sign.ts` before showing a payout as signable. If review throws, the payout is not signable.
- The phone keeps its checked copy of **every** wallet generation of the clan, not just the newest. Signing a move needs the old one (where the coins are) and the new one (where they go).
- Backup words and private keys never leave the phone: not in requests, logs, analytics or plaintext storage.

## Implemented

Feature flag: `CLANS_CLAN_WALLETS_ENABLED` (default off), with `CLANS_CLAN_WALLET_OVERSIGHT_KEYS` (comma-separated public keys). When off, `GET` still works and returns `enabled: false`. The `POST` routes return `503`.

### `GET /api/clans/{clan_id}/wallet`

Any active clan member. Returns the current wallet generation.

```json
{
  "enabled": true,
  "status": "confirming",
  "generation": 1,
  "network": "signet",
  "signer_count": 3,
  "threshold": 2,
  "recovery_threshold": 2,
  "recovery_blocks": 26280,
  "recovery_days": 182,
  "confirmations_required": 3,
  "oversight_keys": ["[a1b2c3d4/87'/1'/0']tpubD...", "[e5f6a7b8/87'/1'/0']tpubD..."],
  "signers": [
    {
      "user_id": "…",
      "display_name": "Amina",
      "key_registered": true,
      "fingerprint": "397a4a50",
      "confirmed": false
    }
  ],
  "me": { "is_signer": true, "key": "[397a4a50/87'/1'/0']tpubD...", "confirmed": false },
  "policy": {
    "network": "signet",
    "oversight": ["[a1b2c3d4/87'/1'/0']tpubD...", "[e5f6a7b8/87'/1'/0']tpubD..."],
    "signers": ["[…]tpub…", "[…]tpub…", "[…]tpub…"],
    "recovery_threshold": 2,
    "recovery_blocks": 26280
  },
  "wallet_code": "8yq3zv5k",
  "activated_at": null,
  "started_by": null,
  "start_reason": null,
  "next": null,
  "earlier": [],
  "alarms_recent": 0
}
```

| Field | Meaning |
|---|---|
| `status` | `not_started` → `collecting_keys` → `confirming` → `active`. The top-level fields describe the wallet in use: the active one, or the first one being set up |
| `next` | `null`, or a new generation being set up while the active one keeps working. It has the same fields as the top level (without `enabled`, `next` and `earlier`) |
| `earlier` | Generations that were active once and are now retired, newest first: `{"generation", "wallet_code", "retired_at", "balance_sats"}`. `balance_sats` is what is still in it, by the chain watcher's last count (`null` before it looked). It drops to `0` once the move goes out |
| `started_by`, `start_reason` | For a generation started with `POST …/wallet/next`: the signatory's display name and the reason. `null` for the first wallet |
| `policy` | `null` until every signatory has a key. `oversight` is a list of 1–3 Afribit keys, any one of which approves; keep its order. Map it to the `ClanPolicy` type: `parseKey()` each key, in both lists; `recovery_threshold` becomes `recoveryThreshold` and `recovery_blocks` becomes `recoveryBlocks`. `signers` is already in canonical order: keep it |
| `wallet_code` | The server's code. For display only: the phone shows and submits its own |
| `me.key` | The key this account registered, so the phone can check it matches the key in its vault |
| `alarms_recent` | How many alarms members should see were raised in the last 30 days, across all of this clan's wallets. Show a banner when it's above `0` (see "Alarms" below) |

### `POST /api/clans/{clan_id}/wallet/keys`

Signatories only (`403` otherwise). Body: `{"key": "[fingerprint/87'/1'/0']tpub…"}` on test networks, `{"key": "[fingerprint/87'/0'/0']xpub…"}` on Bitcoin mainnet (`network: "bitcoin"`). Get it from `keyExpression(signerFromWords(words, view.network).info)`.

- Registers the key in the generation being set up: the first wallet, or `next`.
- Returns the wallet view above.
- Sending the same key again changes nothing.
- A different key replaces this signatory's key and clears **all** confirmations. Everyone re-checks.
- When the last signatory's key arrives, `status` becomes `confirming` and `policy` appears.

| Error | When |
|---|---|
| `400` | Not a valid public key for the wallet's network (`tpub` on `87'/1'/0'` for test networks, `xpub` on `87'/0'/0'` for mainnet); a private key; one of the oversight keys |
| `409` | Another signatory already registered this key; "This is the same wallet as before. A new clan wallet needs at least one new key." (the last key made the new generation identical to an earlier one); "The clan wallet is already active. To change a key, start a new clan wallet." |
| `503` | Clan wallets are switched off |

### `POST /api/clans/{clan_id}/wallet/confirm`

Signatories only. Body: `{"wallet_code": "<the phone's own 8-character code>"}`. Confirms the generation being set up.

- Returns the wallet view.
- When every signatory has confirmed, that generation becomes `active`. Any earlier active one becomes `retired` and moves to `earlier`.

| Error | When |
|---|---|
| `409` with "Your phone computed a different wallet code…" | The codes differ. This is recorded as a `wallet_code_mismatch` alarm. Show a stop screen: do not use this wallet, tell the clan and Afribit |
| `409` | Not in `confirming`, or this signatory has no key yet |
| `422` | Code isn't 8 characters |

### New wallet generation

A clan needs a new wallet when a key must change: a lost or stolen phone, a lost backup, a new signatory, or a new Afribit key. A wallet's keys never change once it's active.

`POST /api/clans/{clan_id}/wallet/next`, body `{"reason": "lost_key" | "stolen_phone" | "signatory_change" | "oversight_change" | "other"}`. Signatories only. Returns the wallet view with `next` filled in.

How it works:

1. Any signatory starts it. The active wallet keeps receiving and paying while the new one is set up.
2. Every current signatory registers a key for the new generation (`POST …/wallet/keys`): the same key as before, or a new one if theirs was lost. At least one key must differ from every earlier generation.
3. Every signatory compares and confirms the new wallet code (`POST …/wallet/confirm`), exactly as at first setup. This is the clan's approval: one signatory alone can't move the money.
4. When the last one confirms, the new wallet becomes `active` and the old one `retired`. New addresses and new grants use the new wallet from then on.
5. The chain watcher then builds a **move** payout from the old wallet to the new one (see [Payout drafts](#payout-drafts)). Signatories and Afribit sign it like any payout. Grants already being paid from the old wallet go first. Grants still waiting for coins are paid from the new wallet.
6. After it confirms, each signatory saves the **new** backup file. Keep the old one too: it still recovers anything paid late to an old address.

A move needs `threshold` signatures from keys of the **old** wallet. A signatory who lost their key can't sign it, so enough of the others must still have theirs. If too few do, the old wallet's coins can still be recovered on the recovery path ([recovery guide](clan-wallet-recovery.md)).

| Error | When |
|---|---|
| `403` | Not a signatory |
| `409` | "Finish setting up the clan wallet first."; "A new clan wallet is already being set up."; an account recovery is waiting |
| `422` | Unknown `reason` |
| `429` | More than 20 starts or cancels an hour |

`POST /api/clans/{clan_id}/wallet/next/cancel`, body `{}`. Signatories only. Stops the setup of `next`. Nothing moves, and the active wallet carries on. `409` "No new clan wallet is being set up." otherwise. A cancelled generation isn't listed in `earlier`; the next one gets a new generation number.

Audit events: `wallet_next_started`, `wallet_next_cancelled`, `wallet_retired`, `wallet_moved`, `wallet_refreshed`.

### Money routes: shared rules

- The money routes need an **active** clan wallet. Before that, `GET` lists return `[]` and the other routes return `409` "The clan wallet isn't active yet."
- With clan wallets switched off, routes that change anything return `503`.
- Money is only credited, and payouts are only built and sent, by the **chain watcher**, a separate worker. The web app never does these.
- Settings: `CLANS_CLAN_WALLET_ESPLORA_URL` (default `https://mempool.space/<network>/api`), `CLANS_CLAN_WALLET_MAX_FEE_SATS` (default 2,000, for grants) and `CLANS_CLAN_WALLET_MAX_SWEEP_FEE_SATS` (default 10,000, for refreshes and moves, which spend many coins).
- Addresses are always in the **active** wallet. Receipts cover every generation, so a late payment to an old address still shows; the chain watcher moves it across.
- Too many requests return `429` "Too many attempts. Please wait a few minutes."

### `GET /api/clans/{clan_id}/wallet/address?purpose=…&grant_id=…`

Any active member. Returns an address in the clan wallet. The server saves it, so the chain watcher knows what it's for:

```json
{"address": "tb1p…", "keychain": "external", "index": 12, "purpose": "repayment", "grant_id": "…"}
```

| `purpose` | Address |
|---|---|
| `grant_funding` | The clan's main address, always index `0`. For Afribit and outside funders |
| `contribution` | One per member, reused each time that member asks |
| `repayment` | One per grant, reused. Needs `grant_id`, and the grant must be `in_recovery` |

Send `grant_id` with `repayment` only.

**The phone must check** `clanOutput(policy, "external", index).address === address` before showing it.

| Error | When |
|---|---|
| `409` | Wallet not active; "This grant has no outstanding repayment." |
| `422` | Unknown `purpose`; `grant_id` missing for a repayment, or sent with another purpose |
| `429` | More than 60 addresses an hour |

### Beneficiary payout address (answers #9)

This replaces the Lightning invoice step for clans with an active wallet. The Lightning destination route now returns `409` "This clan pays grants to a Bitcoin address. Give your address instead."

**1. Quote.** `GET /api/clans/{clan_id}/grants/{grant_id}/payout-quote?address=tb1…`. Beneficiary only. Saves nothing.

```json
{
  "address": "tb1q…",
  "approved_sats": 40000,
  "fee_paid_by": "recipients",
  "estimated_fee_sats": 452,
  "estimated_received_sats": 39548,
  "fee_rate_sat_vb": 2
}
```

The estimate is a guide. The final fee is fixed when the payout is built, and the phone checks it then.

- `fee_rate_sat_vb` can have decimals, such as `1.012`. It's the network's estimate for about an hour, rounded up to BDK's unit (a quarter of a thousandth of a sat/vB), not to a whole number.
- The estimate counts the coins the payout will spend. Payouts spend the clan's largest coins first, and each extra coin adds about 142 vB with 3 signatories (175 with 5, 209 with 7).

**2. Give the address.** `POST /api/clans/{clan_id}/grants/{grant_id}/payout-address` with `{"address": "tb1…"}`, once the beneficiary confirms the quote. Returns the same preview.

- At this moment the grant amount is held back from the clan's confirmed balance, and the grant becomes `awaiting_signatures`. The chain watcher builds the payout draft within about 30 seconds.
- Sending the same address again changes nothing.
- A **different** address, given before the payout goes out, makes a new draft that spends the same coins. The old draft becomes `expired`, and signatories sign the new one.

| Error | When |
|---|---|
| `400` | Not a `tb1…` address; not valid on the clan's network; one of the clan's own addresses |
| `403` | Not the beneficiary |
| `404` | Grant not found in this clan |
| `409` | Grant hasn't passed the vote or been accepted; "Network fees are unusually high"; "The network fee would leave you with too little"; "The clan needs enough confirmed money for this grant."; "This grant has already been sent."; an account recovery is waiting (POST only) |
| `503` | "Bitcoin network information is unavailable": the chain watcher hasn't reported in the last 10 minutes. Show it as a temporary problem and offer to try again |

### Incoming payments (answers #10)

`GET /api/clans/{clan_id}/wallet/receipts?address=tb1…` returns the payments seen at that address, newest first. Any active member can use it. Without `address`, it returns the member's own: payments to their contribution address and repayments of grants they received. Up to 50.

```json
[
  {
    "id": "<txid>:<vout>",
    "txid": "…",
    "vout": 0,
    "address": "tb1p…",
    "purpose": "repayment",
    "grant_id": "…",
    "amount_sats": 20000,
    "confirmations": 1,
    "status": "pending",
    "kes_per_btc": "12500000",
    "kes_credited_minor": null,
    "kes_owed_after_minor": null,
    "credit_note": null
  }
]
```

The last four fields are for repayments of grants owed in KES (see [Grants owed in KES](#grants-owed-in-kes)). They are `null` otherwise.

- `kes_per_btc`: the BTC/KES rate when the watcher first saw the payment, as a decimal string. The payment counts at this rate.
- `kes_credited_minor`: KES cents this payment took off the debt, once `confirmed`.
- `kes_owed_after_minor`: KES cents still owed straight after it.
- `credit_note`: `"waiting_for_rate"` when the payment has its confirmations but no rate was available to count it. It stays `pending` and counts when a rate is available. Show "Confirmed. It counts in KES once today's rate is available."

| Rule | Detail |
|---|---|
| Identity | One receipt per `txid:vout`. The same payment seen twice is the same receipt |
| `status` | `pending`, `confirmed` (once it has `confirmations_required` confirmations, from the wallet view: 3 unless `CLANS_CLAN_WALLET_CONFIRMATIONS` says otherwise), `dropped` (left the chain or was replaced before confirming) |
| Crediting | The ledger credits a payment only when it becomes `confirmed`. A reorg after that is an alarm for Afribit, not a silent reversal |
| Refresh | Poll every 30 seconds while a receipt is `pending`. When one becomes `confirmed`, reload the wallet view and the grant |

The screen still checks the address with `clanOutput()`. A receipt for an address the phone didn't check is not shown as a payment to the clan.

### Grants owed in KES

A grant requested in KES (`POST /api/clans/{clan_id}/grants` with a KES quote) is owed in KES. The clan still pays out the fixed sats from the quote. Grants requested in sats or in another currency, and every grant made before this, are owed in sats as before. Nothing old is rewritten.

Each grant in the clan detail now has:

| Field | Meaning |
|---|---|
| `obligation_currency` | `"KES"` or `"BTC"` |
| `principal_minor` | What the member owes in full: KES cents for a KES grant, sats for a BTC grant |
| `outstanding_minor` | What is still owed, in the same unit. `0` until the grant is paid out |
| `recovered_sats` | Sats repaid so far |
| `outstanding_sats_estimate` | About how many sats are still owed at today's rate, or `null` if no rate is available. Exact for BTC grants |

`outstanding_msat` and `recovered_msat` are kept. For a KES grant they are the sats share of the debt: `outstanding_msat` is `principal_msat × KES still owed ÷ KES owed in full`, rounded up, so it is above zero exactly while KES is still owed.

How a repayment counts:

1. The chain watcher reads the BTC/KES display rate (CoinGecko, at most 5 minutes old) when it first sees the payment, and keeps it with the receipt.
2. When the payment confirms, it is worth `sats × rate` in KES, rounded to the nearest cent. That comes off what's owed. If less than KES 1 is left, the grant counts as repaid.
3. If the payment is worth more than what's owed, only the sats needed to clear the debt count towards the grant. The rest is clan money, recorded as surplus.
4. If no fresh rate is available, the payment is not counted with a guess. It stays `pending` with `credit_note = "waiting_for_rate"` and counts at the next check that has a rate. (The product owner confirmed this rule on 6 November 2026.)
5. The rate, the KES counted and what's still owed are in the payment's Activity item.

The ledger still accounts for every sat. When the sats a KES repayment counts for differ from the sats share of the debt it clears, because the price moved, the difference is booked to `clan_capital` (an `exchange_gain`) or to `exchange_losses` (an `exchange_loss`).

### Wallet backup file

Once the wallet is `active`, every signatory saves a backup file. With it and the 12 words of enough signatories, the clan can recover its money on the recovery path without Clans or Afribit ([recovery guide](clan-wallet-recovery.md)). It holds public keys only.

The phone builds it from the policy **it has already checked** (the one whose wallet code the signatory compared), never from a file the server sends. Field order doesn't matter; field values must be exactly these:

```json
{
  "format": "afribit-clan-wallet-backup/1",
  "network": "signet",
  "clan_id": "…",
  "generation": 1,
  "wallet_code": "8 characters",
  "oversight": ["[fingerprint/87'/1'/0']tpub…"],
  "signers": ["[fingerprint/87'/1'/0']tpub…", "…"],
  "threshold": 2,
  "recovery_threshold": 2,
  "recovery_blocks": 26280,
  "descriptors": {
    "external": "tr(…)#checksum",
    "internal": "tr(…)#checksum"
  }
}
```

- `oversight` and `signers` keep the policy's order.
- Each descriptor is `descriptor(policy, keychain)` followed by `#` and `descriptorChecksum()` of it.
- `python -m clans.recover check backup.json` refuses a file whose fields don't match its keys. The oversight tool writes the same file with `export-backup`.

### Payout drafts

`GET /api/clans/{clan_id}/wallet/payouts` lists drafts, newest first (up to 100). Any active member.

- `status=…` takes one status or several separated by commas. Without it, every status is returned.
- `grant_id=…` returns drafts that include that grant. To find the current draft for a grant, follow `replaced_by` to the end.

`GET /api/clans/{clan_id}/wallet/payouts/{payout_id}` returns one:

```json
{
  "id": "…",
  "clan_id": "…",
  "kind": "grant",
  "generation": 1,
  "destination": null,
  "status": "awaiting_signatures",
  "psbt": "cHNidP8B…",
  "txid": "…",
  "fee_paid_by": "recipients",
  "fee_sats": 452,
  "max_fee_sats": 2000,
  "fee_rate_sat_vb": 2,
  "recipients": [
    {
      "grant_id": "…",
      "name": "Amina",
      "address": "tb1q…",
      "approved_sats": 40000,
      "received_sats": 39548
    }
  ],
  "signatures": { "count": 1, "required": 2, "signed_by_me": false, "names": ["Juma"] },
  "oversight_signed": false,
  "replaces": null,
  "replaced_by": null,
  "created_at": "…",
  "broadcast_txid": null,
  "confirmations": 0
}
```

`psbt` already contains the signatures collected so far. The phone reviews and signs this copy, which adds its signature to the others.

| `status` | Meaning | Screen |
|---|---|---|
| `awaiting_signatures` | Fewer than `signatures.required` signatories have signed | Signatories who haven't signed can review and sign |
| `awaiting_oversight` | The clan has signed; waiting for Afribit | Nothing to sign |
| `broadcasting` | **New.** Every signature is in; the chain watcher sends it within about 30 seconds | Show as sending |
| `broadcast` | Sent; `broadcast_txid` is set and `confirmations` counts up | Poll every 30 seconds |
| `confirmed` | 3 confirmations. The grant is booked and becomes `in_recovery` | Done |
| `expired` | The beneficiary changed the address. `replaced_by` names the new draft | Open the new draft |
| `replaced` | Another version of this payment went out or confirmed instead. `replaced_by` names it | Open the other version |

**Higher-fee versions.** A `broadcast` payout still unconfirmed after `CLANS_CLAN_WALLET_BUMP_AFTER_MINUTES` (default 180) gets a new draft when network fees have risen, or when the network dropped it:

- The new draft is `awaiting_signatures`, with `replaces` set to the sent payout. The sent payout stays `broadcast` meanwhile.
- It spends the same coins at a higher fee, so only one of the two can confirm. The beneficiary pays the extra fee, so `received_sats` is lower.
- Signatories and Afribit sign it like any draft. Clans never raises a fee without fresh signatures.
- When it goes out, the first payout becomes `replaced`. If the first confirms before then, the new draft becomes `replaced`.
- There is at most one waiting higher-fee version per sent payout.

The phone builds a `PayoutExpectation` from this response:

```ts
{
  recipients: recipients.map((r) => ({ address: r.address, amountSats: BigInt(r.approved_sats) })),
  maxFeeSats: BigInt(max_fee_sats),
  feePaidBy: fee_paid_by,
}
```

It runs `reviewPayout(psbt, policy, expectation)`, then `signPayout()`. `policy` is the phone's saved copy of wallet `generation`.

**Refreshes and moves.** `kind` says what a payout is:

| `kind` | What it does | `recipients` | `destination` |
|---|---|---|---|
| `grant` | Pays beneficiaries | The beneficiaries | `null` |
| `refresh` | Sends the oldest coins back to the same wallet, before the 6-month recovery path opens on them. The chain watcher builds one when the oldest coin is about 5 months old | `[]` | `{"generation": <same>, "keychain": "internal", "index": 4, "address": "tb1p…"}` |
| `move` | Sends everything in a retired wallet to the clan's newest wallet | `[]` | `{"generation": <newer>, "keychain": "internal", "index": 0, "address": "tb1p…"}` |

For both, the clan pays the fee (`fee_paid_by: "clan"`), up to `max_fee_sats`. A refresh or move spends up to 25 coins at a time; the next one follows once it confirms. A grant always comes first: a refresh still waiting for signatures gives up its coins to a new grant and becomes `expired`.

The phone checks a refresh or move with its **own** copies of both wallets. Never use `destination.address` from the server:

```ts
const from = savedPolicy(payout.generation);            // where the coins are
const to = savedPolicy(payout.destination.generation);  // where they go: same one for a refresh
if (!to) throw new Error("Confirm the clan's new wallet on this phone first");
const expectation = { destination: to, index: payout.destination.index, maxFeeSats: BigInt(payout.max_fee_sats) };
reviewSweep(payout.psbt, from, expectation);            // then signSweep(…)
```

`reviewSweep()` refuses anything but exactly one output, to that change address, with a fee at most `max_fee_sats` and never above 10,000 sats. A move whose `destination.generation` is not newer than `generation`, or a refresh whose generation differs, is not signable either.

### `POST /api/clans/{clan_id}/wallet/payouts/{payout_id}/signature`

Signatories only. Body: `{"psbt": "<signed copy>"}`. Returns the draft.

- The copy may contain the signatures that were already there. Beyond those, it may add only this signatory's own signature on every input.
- Each new signature is checked against the payment as soon as it arrives.
- Sending the same signed copy again changes nothing.

| Error | When |
|---|---|
| `403` | Not a signatory with a key in this wallet; the payout pays you |
| `404` | Payout not found in this clan |
| `409` | "This signature is for a different payment"; "This payout was replaced. Sign the newest version."; "This payout has already been sent."; "The signed copy contains signatures from other keys"; "The signed copy doesn't include your signature"; "Sign every part of the payment"; "A signature doesn't match this payment. Sign it again."; "This payout's wallet isn't in use."; an account recovery is waiting |

A payout from a retired wallet (a move, or a grant that was already being paid when the new wallet became active) can still be signed. Sign it with that generation's saved key.
| `422` | Body missing or too long |

### `POST /api/clans/{clan_id}/wallet/payouts/{payout_id}/oversight-signature`

For the Afribit oversight tool only. It needs **no session**: the signature is the proof. The server checks each signature, then stores only signatures by an oversight key on this exact payment.

- Body: the tool's `signed.json`, unchanged: `{"id", "clan_id", "txid", "psbt"}`. Only `psbt` is required. Any of the other fields that are present must match this payout (`409` "This signed file is for a different payout.").
- `Content-Type: application/json` is required (`415` otherwise).
- Up to 30 uploads an hour.
- Returns `{"id": "…", "txid": "…", "oversight_signed": true, "signatures": {"count": 2, "required": 2}}`.
- Other errors are as for the signatory route.

The oversight tool's `review` and `sign` commands take the `GET …/payouts/{payout_id}` response as their payout file.

### Communities

Every clan belongs to a community, which oversees its payouts (see [communities.md](communities.md)). Clans without one belong to the default community, Afribit, whose keys and laptop hashes are the settings above. Other communities' keys and hashes are in the `clan_communities` table, which the web role can only read.

- `POST /api/clans` takes an optional `community_code`. A code that doesn't match an open community is `400` "That community code isn't valid. Check it with the community."
- Clan summaries include `community`: `{"id": null, "name": "Afribit"}` for the default, or the community's short id and name.
- A wallet is built with its community's oversight keys, so `oversight_keys` in `GET …/wallet` are that community's. With no keys yet, making the wallet is `409` "<name> hasn't set up an oversight laptop yet, …".
- Each laptop's bearer token belongs to one community. Every `/api/oversight/…` route below returns only that community's clans.

#### `GET /api/oversight/community`

Which community a laptop's token belongs to: `{"name": "Kibera Savers", "oversight_keys": 2}`. The oversight app shows the name on its main screen. `401` and `503` as below.

### `GET /api/oversight/payouts`

For oversight laptops only. Lists every payout in the laptop's community that the clan has signed and that waits for an oversight approval (`status` `awaiting_oversight`), oldest first. Each item is the payout view above, with `signed_by_me` always `false`.

- Header: `Authorization: Bearer <laptop token>`. Each laptop makes its own token with the tool's `connect` command. The server keeps only SHA-256 hashes: Afribit's in `CLANS_CLAN_WALLET_OVERSIGHT_TOKEN_HASHES` (comma-separated), other communities' in their `clan_communities` row.
- The token can list payouts and read the community's report, nothing else. Approving still needs an oversight key's signature.
- `401` for a missing or unknown token; `503` when no token hashes are configured or clan wallets are off; up to 120 requests an hour.

### `GET /api/oversight/report?from=YYYY-MM-DD&to=YYYY-MM-DD&format=json|csv`

For oversight laptops, with the same bearer token and limits as `/api/oversight/payouts`. A report on the laptop's community: one row per clan for the period (`to` is exclusive, at most 366 days, UTC dates). Built from the activity log, sign-ins, grants, debts and the clan ledger; see [reports.md](reports.md).

```json
{
  "from": "2026-11-01", "to": "2026-12-01", "community": "Afribit",
  "clans": [{
    "clan_id": "…", "clan": "Kibera Real Sats", "community": "default", "created_at": "…",
    "members": 3, "signatories": 3, "wallet": "active", "network": "bitcoin",
    "balance_sats": 5404, "active_members": 3, "sign_ins": 9, "actions": 31,
    "by_category": {"members": 5, "wallet": 6, "grants": 6, "money": 8},
    "grants_requested": 1, "grants_paid": 1, "paid_sats": 2530,
    "money_in_sats": 8265, "repaid_sats": 2190,
    "grants_open": 1, "outstanding_sats": 340, "repayment_rate": 0.866,
    "paid_kes": 250.0, "repaid_kes": 216.5, "outstanding_kes": 33.5
  }],
  "totals": {"clans": 1, "members": 3, "paid_sats": 2530, "…": "…"}
}
```

- Period counts: `active_members` (members who signed in or did anything), `sign_ins`, `actions`, `by_category`, `grants_requested`, `grants_paid`, `paid_sats`, `money_in_sats` (deposits and repayments that confirmed), `repaid_sats`, `paid_kes` (KES owed on KES grants paid out), `repaid_kes` (KES counted from repayments of KES grants).
- Now, not per period: `members`, `signatories`, `wallet`, `balance_sats`, `grants_open`, `outstanding_sats`, `outstanding_kes` (KES still owed on KES grants), `repayment_rate` (the share repaid over every grant paid so far, weighted by sats; a KES grant's share is measured in KES; `null` before the first).
- The KES columns are in KES, with up to 2 decimals, and cover KES grants only. The sats columns cover every grant.
- No member names, ids or addresses. `format=csv` gives the clan rows as CSV, without `by_category`.
- `422` for a bad period.

### Alarms

The chain watcher raises an alarm once per cause, for example once per unexpected transaction. A phone that computes a different wallet code (`POST …/wallet/confirm` returning `409`) is listed as an alarm too. Alarms only report: they never change money, and nothing here marks them resolved.

#### `GET /api/clans/{clan_id}/wallet/alarms`

Any active clan member, not only signatories. The 50 newest alarms members should see, across all of the clan's wallet generations, newest first. `403` for someone outside the clan.

```json
[
  {
    "id": "…",
    "kind": "unapproved_spend",
    "reference": "4f1c…e9a0",
    "clan_id": "…",
    "generation": 1,
    "created_at": "2026-11-05T09:12:44.512301+00:00",
    "members": true,
    "message": "Money left the clan wallet without an approved payout. Afribit is looking into it. Don't approve anything until Afribit has explained it.",
    "detail": {}
  }
]
```

| Field | Meaning |
|---|---|
| `kind` | See the table below. Show `message` for kinds the app doesn't know |
| `reference` | What the alarm is about: usually a transaction id. For `wallet_code_mismatch`, the wallet's id |
| `generation` | The wallet generation it concerns. It can be an earlier one |
| `message` | Plain English, ready to show |
| `detail` | Extra facts, which differ by kind. `wallet_code_mismatch` has `signer_id` and `phone_code` |

| `kind` | Members see it | Means |
|---|---|---|
| `unapproved_spend` | Yes | Money left a clan wallet in a transaction Clans didn't build. Every key holder for that wallet should stop approving until Afribit has explained it |
| `wallet_code_mismatch` | Yes | A signatory's phone computed a different wallet code during setup |
| `invalid_signature` | Yes | An uploaded signature didn't verify and was set aside |
| `address_mismatch` | Yes | A stored address doesn't match the wallet. It isn't used |
| `recovery_path_open` | Yes | A coin reached the 6-month recovery wait before it was refreshed |
| `receipt_reorg` | Yes | A payment the clan had counted disappeared from the blockchain |
| `payout_reorg` | Yes | A confirmed payout disappeared from the blockchain |
| `payout_accounting` | No | A payout confirmed but couldn't be booked in the ledger |
| `sweep_blocked` | No | A refresh or move couldn't be built, usually because fees are above the sweep limit |

#### `GET /api/oversight/alarms?since=…`

For oversight laptops, with the same bearer token as `GET /api/oversight/payouts`. Every alarm in the laptop's community, including the ones members don't see, newest first, at most 200. Each item also has `clan_name`.

- `since` (optional): an ISO date and time. Only alarms after it are returned. A time without a zone is read as UTC. `422` if it isn't a date and time.
- `401` for a missing or unknown token; `503` when no token hashes are configured or clan wallets are off.
- The tool's `alarms` command uses it, and `approve` shows new alarms before any payout.

#### `GET /api/oversight/wallets`

For oversight laptops, with the same bearer token. Every active clan wallet in the laptop's community: `{clan_id, clan_name, generation, policy}`, where `policy` is the same as in `GET /api/clans/{clan_id}/wallet`. The tool's `add-wallet` command uses it, and registers a wallet only after the 8-character code read by phone matches. `401` and `503` as above.

### Activity

Every member sees their clan's activity. Each item has a plain title and explanation from the server, so the app never shows a generic "Clan updated".

#### `GET /api/clans/{clan_id}/activity?month=YYYY-MM&timezone=Africa/Nairobi&cursor=…&limit=25`

Unchanged paging. Each item now also has `title`, `category` and `summary`:

```json
{"id": "…", "event": "wallet_key_registered", "actor": "Amina Organizer", "at": "…",
 "title": "Added a signing key", "category": "wallet",
 "summary": "Amina Organizer made a signing key on their phone and added it to the clan wallet. …",
 "data": {}}
```

Categories: `clan`, `members`, `grants`, `money`, `wallet`, `security`, `account`. `data` keeps only amounts, as before. An event type the server doesn't know yet is titled "Clan activity".

#### `GET /api/clans/{clan_id}/activity/{event_id}`

One event, for its own page: the list fields plus `details` and `links`.

```json
{"id": "…", "event": "payout_signed", "actor": "Wanjiru Tailor", "at": "…",
 "title": "Signed a payment", "category": "money",
 "summary": "Wanjiru Tailor checked the payment on their phone and signed it with their key.",
 "details": [{"label": "Key fingerprint", "value": "9c0b6c6d"}],
 "links": {"payout_id": "…", "txid": "f4b6…"}}
```

- `details` is a short list of safe facts, already worded: amounts, fees, key fingerprints, wallet codes and versions. Never addresses, phone codes or internal ids.
- `links` can hold `grant_id` (open that grant), `payout_id` (open that payment) and `txid` (link to a block explorer for the wallet's network).
- Members of that clan only: `403` for others, `404` for an event in another clan or a malformed id. Shares the activity limit of 120 requests a minute.

## Planned

### Lightning till (Phase 4)

`GET /api/clans/{clan_id}/till` returns:

```json
{
  "enabled": true,
  "balance_sats": 52000,
  "cap_sats": 200000,
  "sweep_at_sats": 100000,
  "last_sweep": { "txid": "…", "amount_sats": 100000, "at": "…" }
}
```

Repayment invoices from the till reuse the existing deposit flow (`POST /api/clans/{clan_id}/deposits`). It returns `method: "lightning"` while the till is below its cap, and `method: "onchain"` with an address once it's full.

**Shapes (answers #10).** The `lightning` response keeps today's deposit fields plus `"method": "lightning"`. The `onchain` response is exactly the address response above plus `"method": "onchain"`: `address`, `keychain`, `index`, `purpose` and `grant_id`. So the phone runs the same `clanOutput()` check before showing it, and tracks it through `receipts`. Never show a Lightning invoice unless `method` is `lightning`.

## Answers to the other frontend questions

- **Restored or new phone on an active wallet (#8):** your approach is right. The phone compares codes with the group and saves its local check. The server records nothing new, and the member's existing confirmation stands.
- **`generation: null` before setup (#7):** that's intended. It becomes a number once the first key is registered.
- **Vault keyed by clan only, and generations (#10, updated):** the vault holding the 12 words can stay keyed by clan. Most members keep the same key in the new generation, so their one key signs both the move and later payouts. A member who lost their phone sets up a new key on a new phone and registers it for the new generation. They can't sign the move, and don't need to: enough of the others sign it. **The saved wallet check is different.** It must be kept per generation (clan + generation), because a move is checked against both the old wallet and the new one. Keep each generation's check until its `earlier` entry shows `balance_sats: 0`, and keep it after that too: it is small, and a late payment to an old address would need it.
