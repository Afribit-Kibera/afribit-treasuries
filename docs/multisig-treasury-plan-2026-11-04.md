# Plan: clan multisig wallets inside the Clans app

**Date:** 4 November 2026
**Status:** Approved direction. Phase 0 is done and Phase 1 has started on branch `feat/multisig-treasury`. Clan wallets are off until the operator turns them on, and use Bitcoin mainnet unless set to a test network ([mainnet.md](mainnet.md)).
**Audience:** Afribit Clans owner, developers and security reviewers.
**Related:** [API contract](clan-wallet-api.md) · [frontend jobs](frontend-jobs-clan-wallet.md)

## Owner decisions, 4 November 2026

| Question | Decision |
|---|---|
| Recovery rule | A majority of signatories after about 6 months (26,280 blocks) |
| Who pays payout fees | **The beneficiary.** The network fee comes out of the grant, so they receive the approved amount minus the fee. They still owe the full approved amount |
| Lightning till | **Yes, with a cap**, if it meets the security conditions below |
| Existing BTCPay balances | Move them into each clan's new wallet |
| Who builds what | The screens are built from the [job list](frontend-jobs-clan-wallet.md). The backend, key storage, oversight tool and till are built on this branch |
| Phone key unlock | A passkey where the phone supports it, otherwise a **6-digit PIN** |
| Till caps | 200,000 sats per clan, swept to the clan wallet at 100,000, and **2,000,000 sats across all tills** |
| Oversight practicality | Up to three Afribit oversight keys, **any one** of which approves. Each staff member who does oversight has their own key, so no one shares a seed and payouts don't wait for one person |
| Oversight hardware | **None for now.** Software keys on Afribit's two existing laptops, in a separate Windows account. Ledgers later |

## Decision

Clans stops holding clan money. Each clan gets its own Bitcoin multisig wallet. Signatories hold their keys on their own phones, inside the Clans app. Clans keeps everything it does today (accounts, votes, grants, repayments, the KES ledger, limits and the Activity view) and only ever holds **public keys**.

This replaces BTCPay and the dedicated LND node as the place where clan money lives. A hacked Clans server, database or frontend can no longer move clan funds.

The app's look, screens and governance flow stay as they are. The approval step changes underneath: a signatory's approval becomes a real Bitcoin signature instead of a passkey assertion that the payment worker checks.

## Why

- The current custody is honest but weak: "the node operator retains spending authority. This is not Bitcoin multisignature custody." ([README](../README.md))
- BTCPay installations have been attacked this year. The [BTCPay 2.4.2 advisory](https://blog.btcpayserver.org/security-advisory-btcpay-server-2-4-2/) covered actively exploited LND credential leaks, and [Blink's custodial accounts were drained on 19 September 2026](https://cryptobriefing.com/blink-wallet-pauses-custodial-breach/). Running a hot node for community funds is a standing risk.
- Most of the recent security work (dispatch secrets, signer trust manifests, worker authorizations) exists only because the server can spend. When the server can't spend, that whole class of risk goes away.

## How a clan wallet works

Each clan wallet is one Taproot address type with two ways to spend and no third "master key" way:

| Path | Who must sign | When |
|---|---|---|
| **Normal** | One of Afribit's oversight keys (up to three) **and** a majority of signatories (2 of 3, 3 of 5, 4 of 7) | Any time |
| **Recovery** | A majority of signatories, without Afribit | Only after about 6 months (26,280 blocks) with no spending from those coins |

What this gives us:

- **A hacked Clans server can't steal.** Every signatory loads the app's code from our server, so a compromised server could try to copy keys from all phones at once. The oversight key never touches the web app: it lives on a separate hardware signing device. The attacker still cannot spend.
- **Afribit alone can't spend.** Even all of Afribit's oversight keys together can't: the normal path also needs the clan's majority.
- **Afribit can't freeze a clan's money.** If Afribit disappears or refuses, the signatories use the recovery path after the waiting period.
- **No lock-in.** The wallet is a standard [miniscript descriptor](https://bitcoin.sipa.be/miniscript/). Signatories can recover it with their backup words in Bitcoin Core, without Clans.
  - Correction to an earlier draft: [Liana](https://github.com/wizardsardine/liana) probably can't open this wallet. Liana expects the main spending path to be a plain "k of n" group, and ours requires one specific key (Afribit's) plus a majority. We'll test Liana and Bitcoin Core in the pilot, and the recovery rehearsal will use whichever works.

The waiting period counts from when coins arrive. Active clans refresh it naturally, because every payout sends change to a new address. For a clan with no payouts, Clans must schedule a refresh (a payment from the wallet to itself, signed by the normal path) before about 5 months. Each refresh costs one network fee.

### Who does what

| Role | Holds | Does |
|---|---|---|
| Signatory | Their own key on their phone, plus 12 backup words on paper | Approves and signs payouts after checking them on their phone |
| Afribit oversight | One to three keys, each held by one staff member on their oversight laptop (see below) | Signs only payouts that match an approved grant; checks the payment independently |
| Clans server | Public keys only (watch-only) | Creates addresses, watches the blockchain, builds unsigned payments, collects signatures, broadcasts, records everything in the ledger |
| Members | Their usual personal wallets | Send contributions and repayments; receive grants |

### Main flows

1. **Setup.**
   - Each signatory opens Clans and creates a key, then writes down 12 backup words. These are separate from the existing account recovery words, which never become Bitcoin keys.
   - The server combines all the public keys into the clan wallet and shows an 8-character **wallet code**. Every signatory checks the code matches on their own phone before anyone deposits.
2. **Money in.**
   - Every grant gets its own repayment address, and every member can get their own contribution address. Clans credits each payment automatically to the right person and grant.
   - Afribit's large grants go to the clan's main address.
   - Clans counts money only after confirmations. Unconfirmed deposits are shown as pending.
3. **Money out.**
   1. Members vote as they do today and the beneficiary accepts.
   2. The server builds the exact payment: destination, amount and fee.
   3. Each signatory's phone rebuilds the clan's addresses from the wallet it saved at setup. It refuses to sign if anything differs from the approved grant: another destination, a wrong amount, a fee above the limit, or change going anywhere except the clan's own wallet.
   4. Afribit's oversight tool does the same check against its own records, and signs.
   5. The server combines the signatures, checks the result again and broadcasts it.
4. **Unapproved spend alarm.** Any money leaving the wallet that doesn't match an approved payout is flagged to all members and Afribit. This shouldn't be possible without the oversight key, so it would mean a key compromise or a recovery-path spend.
5. **Lost phone or departing signatory.**
   - A signatory who loses their phone can restore their key from their backup words.
   - Changing the roster means creating a new wallet and moving the funds with one normal-path payment.

## Afribit oversight in practice

**Is it needed for every payout?** Yes. Every normal payout needs one oversight signature, which is what stops a hacked Clans server from emptying wallets. The only payouts without it are recovery-path spends, after the 6-month wait.

**Where the key lives: our existing laptops, for now.** Owner decision: no hardware purchase for the pilot. Each oversight person holds a software key on one of Afribit's two existing laptops, inside a separate Windows account used only for oversight. Ledgers can replace these keys later. The setup steps are in the [oversight laptop guide](oversight-laptop-setup.md).

The key must never be in the Clans app. If it lived there, one hacked server update could copy it together with the signatories' keys, and the oversight step would protect nothing. A separate laptop account that never loads the Clans app keeps it out of reach.

- **Several keys, any one approves.** A wallet can name up to three Afribit oversight keys. Each person has their own key and backup words. Nobody shares a seed, and payouts don't wait for one person to be back.
- **Nothing goes offline.** The laptops stay on the internet. The key is stored encrypted with the person's passphrase and decrypted in memory only while signing.
- **Losing a laptop isn't an emergency.** The key file is encrypted, and the person restores the key on another laptop from their paper backup words. The other person's key keeps working meanwhile.

**The Afribit oversight tool** (`python -m clans.oversight`, built). It trusts its own records, not the Clans server:

- **Clan wallets:** each one is registered once, after a signatory reads the wallet code from their phone. Every payout is then checked against the saved wallet: right amounts, and change only to the clan's own change addresses.
- **Beneficiary addresses:** each one is confirmed by phone before first use (see the rules below).
- **No double payments:** a grant is signed once. A higher-fee replacement is allowed only when it spends the same coins, so only one version can confirm.
- **Fee limit:** the laptop's own fee limit applies whatever the server asks for (5,000 sats by default).
- **Large payouts:** above 100,000 sats by default, the person types the full amount to confirm.

**What a software key gives up compared with a Ledger.** If malware takes over the oversight account while the person types their passphrase, it can sign. It would still need the clan majority, so an attacker would have to break both the Clans server and an oversight laptop. That's why the oversight account stays clean: no email, browsing, developer tools, AI agents or browser extensions. Revisit Ledgers before mainnet, based on how much the clans will hold.

**Later option: an automatic co-signer for small payouts.** One of the three oversight keys could belong to a separate service that signs small, routine payouts on its own, for example under 20,000 sats, 12 hours after the clan signs, unless a staff member vetoes it. The trade-offs:

- It must run on its own server, with its own records. If it trusted the Clans server, a hacked server could feed it fake grants.
- Bitcoin itself can't limit the amount this key signs. Only that service's software enforces the limit.
- Large payouts and new beneficiary addresses would still go to a person.

Add it only if daily oversight becomes a burden.

**Day to day:**

1. Clans notifies the oversight person when a payout has its clan signatures.
2. Once a day, or when notified, they sign in to the oversight account and open the tool. Payouts are batched, so this is usually one session.
3. The tool shows each payout: beneficiary, approved amount, amount received after the fee, and address. It refuses anything that doesn't match its records.
4. The person checks the details against what they know about the grant, confirms, and enters their passphrase.
5. The signature goes back to Clans, and Clans broadcasts the payment.

This takes about 5–10 minutes a day.

**Two rules that make oversight meaningful:**

- **Beneficiary addresses are checked outside Clans.** A hacked server could swap a beneficiary's address and show every phone the swapped one. The first time a beneficiary uses an address, the oversight person phones them. The beneficiary reads, from their own wallet, the 6 characters after the start (`tb1q` or `tb1p`) and the last 6. The tool saves the address only if both match. Faking an address that matches 12 characters isn't practical.
- **Afribit funds clans only at addresses the oversight laptop works out.** Large grants to a clan go only to an address from `clan-address`. The tool computes it from the wallet it registered, never from what the server shows.

**Backup and availability:**

- Each person keeps their 12 backup words on paper, in a safe place away from the laptop. Never photographed, never typed anywhere else.
- Separate keys for separate people, never copies of one seed.
- At least two trained Afribit people do oversight, so payouts don't stall when one is away.
- If every oversight key were lost with no backup, clans would wait out the 6 months and use the recovery path.

**Later, with Ledgers:**

- Check that the Ledger registers and signs our exact wallet. To make that possible, wallets already use an extended-key form of the unspendable key.
- Moving a clan to Ledger keys means a new wallet generation and one payment to move the funds.

## Lightning and fees

The clan wallet is on-chain, so every payment into or out of it is a Bitcoin network payment with a fee. Members don't need to change wallets for this. Popular Lightning wallets can both send to and receive from Bitcoin addresses.

### Grants to beneficiaries with Lightning wallets

The beneficiary gives a Bitcoin receiving address from their own wallet. Phoenix, Blink and Breez-based wallets such as Glow all provide one. The clan pays that address, and the money shows up as a normal balance in the beneficiary's wallet.

Fees:

- **Network fee:** paid by the beneficiary out of the grant. The grant screen shows "you'll receive about X", and the signing screen shows the fee in sats and KES.
- **Beneficiary's wallet fee:** some wallets charge to convert an on-chain deposit into Lightning. Phoenix charges only the mining fee, which can be under 500 sats when the network is quiet ([ACINQ](https://acinq.co/blog/phoenix-splicing-update)). Clans should explain this on the grant screen.

### Repayments and contributions from Lightning wallets

- **Now:** the member sends from their Lightning wallet to the grant's repayment address. Phoenix and most Lightning wallets can send on-chain, and the member pays that send fee.
- **Phase 4: a clan "Lightning till" (approved, with a cap).**
  - Each clan gets a small Lightning wallet built on the Breez SDK (Spark), with no node and no channels.
  - It takes instant, cheap Lightning repayments through invoices tied to the grant, as today.
  - It moves its balance into the clan's multisig automatically at 100,000 sats, or weekly when fees are low.
  - Hard cap: 200,000 sats per clan, plus 2,000,000 sats across all clans. Above the cap, Clans shows the on-chain address instead.

### Lightning till security

The till is **not** as safe as the multisig. It's the one place where a server compromise can cost money. It's acceptable only because the amounts are small and capped.

| Risk | Control |
|---|---|
| Server hacked: the attacker spends till balances | Per-clan and total caps; automatic sweeps keep balances low. The till key lives only in the treasury worker, on a separate host and account from the web app, never in the web environment. Most an attacker can take: the sum of current till balances |
| Spark operators (currently Lightspark, Breez and Flashnet) collude or delete data wrongly | Spark's model relies on operators deleting old key material ([Spark's trust model](https://www.spark.money/research/spark-statechain-operator-trust-assumptions)). Keep balances small, and store exit data durably, as [Turnkey recommends](https://docs.turnkey.com/features/networks/spark) |
| Operators offline: no Lightning payments | Members fall back to the clan's on-chain address. The till can exit to the chain with pre-signed transactions, which needs the exit data stored above |
| A sweep sent to the wrong place | Sweeps go only to clan wallet change addresses that the worker derives itself from the stored wallet, never to an address supplied by the API |
| Member confusion | The repayment screen says when money sits in the till and when it reached the clan wallet. Each sweep shows in the Activity ledger |

The till ships only after the multisig pilot (Phase 2) passes, and after the external review has covered it.

### Swap services are not part of the plan

Swap services can turn an on-chain payment into a Lightning payment directly. The main one, Boltz, [suspended its swaps on 3 August 2026](https://www.tftc.io/boltz-bitcoin-swaps-suspended-ai-attacks) and changed hands. We won't depend on any swap service. If a reliable one returns, we can add it as an option for grant payouts, after checking who controls refunds when a swap fails.

### Fee sizes, measured on this branch

Signed payout sizes, measured with the Phase 0 code:

| Clan | 1 payee | 3 payees in one payment | Extra coin spent |
|---|---|---|---|
| 3 signatories | 226 vB | 312 vB | +142 vB |
| 5 signatories | 260 vB | 346 vB | +175 vB |
| 7 signatories | 294 vB | 380 vB | +209 vB |

Fee = size × network fee rate. At 2 sat/vB, a single payout costs about 450–590 sats. At 20 sat/vB it's about 4,500–5,900 sats. The rate changes with demand, so the app always shows the live figure.

### Fee rules

1. **Batching:** non-urgent payouts go out together once a day or week. Three payees in one payment cost about half as much as three separate payments.
2. **Who pays: the beneficiary** (owner decision). The network fee comes out of the payout:
   - On a 40,000-sat grant at 2 sat/vB, the beneficiary receives about 39,550 sats.
   - In a batch, the fee is split equally between beneficiaries.
   - The clan pays out exactly the approved total.
   - The beneficiary still owes the full approved amount; the fee is recorded as their cost in the ledger.
   - Phones and the server check this exact rule before signing.
   - Payouts that would leave a beneficiary under 1,000 sats are refused.
   - Built in `clan_wallet.py` and `vault/sign.ts` (`fee_paid_by="recipients"`).
3. **Fee limit:** every approved payout carries a maximum fee. Phones and the server refuse payments above it.
4. **Timing:** schedule sweeps, refreshes and coin consolidation when fees are low.
5. **Small payments:** advise against on-chain repayments below a minimum, for example 5,000 sats. Point those members to the Lightning till once it exists.
6. **Stuck payments:** a payment stuck at a low fee gets a new, higher-fee version, which needs fresh signatures. Clans never retries a payment silently.
   - Built in the chain watcher: after `CLANS_CLAN_WALLET_BUMP_AFTER_MINUTES` (default 3 hours) unconfirmed, when fees have risen or the network dropped the payment.
   - Same coins, the old fee plus at least 1 sat per vbyte (the network's replacement rule), and never above the payout's fee limit.
   - Refreshes and moves get higher-fee versions the same way.

## Code changes

| Area | Change |
|---|---|
| Accounts, voting, grants, KES ledger, limits, Activity, recovery, design | **Keep** |
| `clan_wallet.py` and the vault signer | **Built in Phase 0** (below) |
| Database: clan wallets, signer keys, confirmations | **Built** (migration `20261104_09`) |
| API: register signer key, wallet status, wallet code check | **Built** ([wallet_api.py](../backend/src/clans/wallet_api.py)), off by default |
| Database and API: deposit addresses, beneficiary payout address, payout drafts, signatures, broadcast | **Built** (migration `20261105_10`, [wallet_money_api.py](../backend/src/clans/wallet_money_api.py)), as specified in the [API contract](clan-wallet-api.md) |
| Phone key store (passkey or PIN encryption) | **Built** ([vault/store.ts](../frontend/src/vault/store.ts)) |
| Afribit oversight tool (software key; Ledger later) | **Built** ([oversight.py](../backend/src/clans/oversight.py), [setup guide](oversight-laptop-setup.md)). The laptop downloads waiting payouts with a read token of its own, then checks, signs and uploads them (`connect`, `pending`, `approve`) |
| Migration of BTCPay balances | **Add** (Phase 3), see below |
| Chain watcher worker reading a block explorer (signet first, then our own explorer) | **Built** ([chain_watcher.py](../backend/src/clans/chain_watcher.py)); replaces the Lightning parts of `treasury_worker.py` after migration |
| Signing screens: create key, show backup words, compare wallet code, review and sign payout | **Add** using existing components and styles |
| `treasury_provider.py` (BTCPay), invoice creation, payout dispatch, dispatch secret, signer trust manifest | **Retire** after migration |

### Phase 0: built on this branch

- [backend/src/clans/clan_wallet.py](../backend/src/clans/clan_wallet.py)
  - Wallet rules with input checks: 3, 5 or 7 distinct signatories, majority threshold, recovery threshold and waiting period, test networks only.
  - Watch-only wallet using BDK (`bdkpython` 3.1.1): addresses, read-only sync from a block explorer, building payouts on the normal path only, strict output and fee checks, and combining signatures.
- [frontend/src/vault/](../frontend/src/vault/)
  - On-phone key creation from 12 words.
  - The same wallet rules and addresses rebuilt from public keys.
  - The wallet code, using the standard descriptor checksum.
  - Review-then-sign of payouts with `@scure/btc-signer` 2.4.1.
- Tests:
  - [test_clan_wallet.py](../backend/tests/test_clan_wallet.py) proves that oversight plus a majority can spend. It also proves that signatories alone, oversight plus one, or signatures for a different payment can't. Wrong destinations, amounts, fees and unconfirmed coins are refused.
  - [test_clan_wallet_interop.py](../backend/tests/test_clan_wallet_interop.py) runs the phone code against BDK. Both sides must produce the same keys, wallet, wallet code and addresses, and phone signatures plus the oversight signature must complete a payment. The phone must refuse redirected, foreign-wallet, over-fee and wrong-amount payments, and keys that aren't in the clan.

Nothing in Phase 0 is wired into the live app or touches mainnet.

### Phase 1 so far

- **Per-wallet unspendable key:** each wallet's unspendable internal key is the BIP-341 point with a chain code derived from the wallet's own keys. Wallets no longer share a visible marker, and Ledger can register them. Phone and server produce the same key: tested.
- **Beneficiary pays the fee:**
  - Payouts subtract the fee from what beneficiaries receive, keeping the same coins so the fee settles exactly.
  - The phone refuses a payout that doesn't follow the agreed fee rule, including a full-amount version.
- **Several oversight keys:** a wallet names one to three Afribit keys, and any one of them plus the clan majority can spend. Two Afribit keys without the clan majority can't. Phone and server agree on these wallets: tested.
- **Wallet setup API**, behind `CLANS_CLAN_WALLETS_ENABLED` with `CLANS_CLAN_WALLET_OVERSIGHT_KEYS` (comma-separated):
  - Signatories register public keys.
  - The wallet is built when all keys are in.
  - Each signatory confirms with the code their phone computed.
  - A different code is refused and recorded as an alarm.
  - Changing a key before activation clears every confirmation.
  - Keys are fixed once the wallet is active.
  - Tests: [test_clan_wallet_api.py](../backend/tests/test_clan_wallet_api.py).
- **Money routes** ([wallet_money_api.py](../backend/src/clans/wallet_money_api.py)):
  - Deposit, contribution and repayment addresses come from the clan wallet. The server stores each one it hands out, and the phone checks it.
  - The beneficiary gives a Bitcoin address after the vote. The grant amount is held back from the confirmed balance at that moment, so two grants can't count on the same money.
  - Signatories upload signed copies. Afribit's oversight tool uploads its copy without a Clans session: the signature itself is the proof.
  - Every new signature is checked against the payment when it's uploaded, so a forged copy is refused and can't replace a good one.
  - Oversight laptops list payouts waiting for Afribit with a read token each (`CLANS_CLAN_WALLET_OVERSIGHT_TOKEN_HASHES`). The token can't approve anything.
  - The web app never credits money, builds payouts or broadcasts.
- **Chain watcher** (`python -m clans.chain_watcher`, one instance at a time):
  - Runs as [afribit-clans-chain-watcher.service](../ops/afribit-clans-chain-watcher.service) under its own account, `afribit-clans-chain`. Its settings are in `/etc/afribit-clans/chain-watcher.env`: the worker database role, with no BTCPay credentials. Provisioning that account and file is still a manual step.
  - Reads the chain tip every 30 seconds, and a wallet on a new block, on activity or every 5 minutes. Settings: `CLANS_CLAN_WALLET_ESPLORA_URL` (Esplora APIs tried in order, see [mainnet.md](mainnet.md#block-explorers)) and `CLANS_CLAN_WALLET_MAX_FEE_SATS` (default 2,000).
  - Credits a deposit or repayment once it has 3 confirmations, only at an address it derives itself from the wallet.
  - Builds payout drafts from coins with 3 confirmations. A changed beneficiary address gets a new draft that spends the same coins, so both versions can never be paid.
  - Checks every signature with BDK before broadcasting, and drops any that fail.
  - Books the grant and the debt once the payout has 3 confirmations. A payment stuck in the network is re-sent as it is, never reset.
  - Raises an alarm, recorded once, for money leaving without a payout, a credited payment or payout disappearing from the chain, a bad signature, or an address the wallet doesn't recognise.
  - Tests: [test_clan_wallet_payments.py](../backend/tests/test_clan_wallet_payments.py) runs a full grant: deposit, vote, address, two signatures, oversight, broadcast, booking and repayment.

- **Recovery without Clans** ([recover.py](../backend/src/clans/recover.py), [guide](clan-wallet-recovery.md)):
  - A public wallet backup file. Phones save it (frontend job F9) and oversight laptops export it (`export-backup`).
  - An offline tool checks the backup, lists coins and their wait, builds a sweep on the recovery path, signs it with a signatory's 12 words and sends it.
  - Tests ([test_recover.py](../backend/tests/test_recover.py)): two of three signatories recover without Afribit; one signatory can't; Afribit's key can't sign the recovery path; a damaged backup or a changed sweep is refused.
  - Bitcoin Core can watch the wallet from the backup. Signing in Core isn't tested yet.

- **New wallet generations, moves and refreshes** (migration `20261105_11`; [API contract](clan-wallet-api.md#new-wallet-generation)):
  - **Who approves a new wallet:** any signatory starts one. Every signatory then registers a key and confirms the new wallet code, as at first setup. The move itself is signed like a payout: the clan majority plus Afribit. There's no separate clan vote, because unanimous confirmation is already stricter. One can be added in front if the pilot wants it.
  - The current wallet keeps working until the new one is active. Then the old one is retired but still watched, and the chain watcher builds one payment moving its coins to a change address of the new wallet. Late payments to old addresses are moved too.
  - Grants already being paid from the old wallet go first. Waiting grants are paid from the new wallet.
  - **Refresh:** when a wallet's oldest coin reaches about 5 months (the recovery wait minus a sixth), the chain watcher builds a payment of up to 25 of the oldest coins back to the same wallet, so the recovery path stays closed. A grant takes precedence and can take a refresh's coins while it still waits for signatures. A coin that reaches the full wait raises a `recovery_path_open` alarm.
  - The clan pays fees for both, up to `CLANS_CLAN_WALLET_MAX_SWEEP_FEE_SATS` (default 10,000). They are booked as network fees.
  - Phones (`reviewSweep()`) and oversight laptops (`review`) derive the destination from their own copy of the target wallet, and refuse anything with more than one output. The laptop needs the new wallet registered with `add-wallet` before it can sign a move.
  - Tests: [test_wallet_moves.py](../backend/tests/test_wallet_moves.py) runs a lost phone end to end: new wallet, a grant paid from the old wallet first, the move, a late payment, then a grant from the new wallet signed with the new key. It also covers refresh timing, a stuck move, and the laptop's checks. [test_clan_wallet_interop.py](../backend/tests/test_clan_wallet_interop.py) checks phone and BDK agree on a move and a refresh.
  - Retired wallets stay watched indefinitely. That's fine at pilot scale; revisit when there are many clans.

- **Alarms for members and Afribit** ([API contract](clan-wallet-api.md#alarms)):
  - Members see the alarms about their money in the app (`GET …/wallet/alarms`, and `alarms_recent` on the wallet card). Frontend job F11 covers the screens.
  - Oversight laptops read every clan's alarms. `approve` shows new ones before any payout and stops unless the person types `yes`.
  - Alarms only report. There's no push or email yet: someone has to open the app or run the tool. Adding email or SMS for `unapproved_spend` is a pilot follow-up.

- **Database permission checks:**
  - Production runs the web app and the chain watcher as separate PostgreSQL roles, each with only the table and column permissions it needs. SQLite tests can't enforce those, so three gaps had slipped through: the web app couldn't clear confirmations when a key changed (so wallet setup would have failed at the last signatory's key on PostgreSQL), and the chain watcher couldn't update a wallet's balance or move a waiting grant to a new wallet. All three are fixed in `database_roles.py`.
  - The wallet tests now check every statement against the production permissions, as the role that runs it ([role_grants.py](../backend/tests/role_grants.py)). A missing permission now fails a test instead of failing in production.

### Moving existing BTCPay balances

Clan balances today sit in the shared Lightning node's channels. The README rule applies: uncertain payments are never resolved by resetting status or removing reservations.

1. Activate each clan's new wallet first: keys, wallet code, and registration on both oversight laptops.
2. Pause new Lightning deposits and payouts, and let pending ones settle or expire. Resolve any uncertain payment from the node's own records first.
3. Reconcile the ledger with the node: each clan's balance must match its recorded share.
4. Close the node's channels cooperatively, so the funds arrive in the node's on-chain wallet.
5. Send one batched on-chain payment that pays each clan's balance, minus its share of the fee, to an address in that clan's wallet that both oversight laptops compute from their registered wallet (`clan-address`). Record one journal entry per clan.
6. Members see the move in the Activity ledger. Lightning repayments resume once the till is live.

Closing fees and the batch fee are shared in proportion to balances. Swap services are not used (see above).

### BDK quirk found in Phase 0

BDK 3.1.1 crashes when finalizing a payment that spends **unconfirmed** coins from a wallet with a time-locked path. Clans spends only confirmed coins (the default), and uses the library's standalone finalizer. BDK's built-in test signer also signs only one place where the same key appears. That doesn't affect phones, which use our own signer and sign only the normal path.

## Phases and gates

| Phase | Work | Done when |
|---|---|---|
| 0 | Wallet rules, watch-only wallet, phone signer, cross-checks | **Done on this branch** |
| 1 | Database, API, chain watcher, signing screens, key storage (passkey-protected on supported phones, PIN fallback), oversight tool on the existing laptops | A signet clan can complete setup, deposit, vote, sign, payout and repayment in the app, with oversight signed on an Afribit laptop |
| 2 | One real group on signet | Full cycle done by real members. Recovery rehearsed from backup words in Bitcoin Core without Clans (and Liana, if it can open the wallet). One lost phone and one refresh rehearsed. Time, errors and fees recorded |
| 3 | External security review, then mainnet with small limits | Review findings fixed. BTCPay deposits paused and existing balances settled. Custody text in the app and on the public page updated |
| 4 | Lightning till, batching scheduler, own block explorer | Measured fees and member feedback justify each one |
| Later | FROST threshold signing for the normal path | The Bitcoin FROST standard is final and libraries are audited |

My rough estimate for Phases 1–2 is 4–8 weeks. Phase 3 depends on the reviewer.

## Security notes for reviewers

- **Phone key storage:**
  - Keys are encrypted at rest. On supported phones the passkey protects them through the WebAuthn PRF extension (Android with Google Password Manager, iPhone with iCloud Keychain on iOS 18 or later). Other phones use a 6-digit PIN.
  - A 6-digit PIN stops casual access, not someone who copies the phone's storage and tries every PIN. That is accepted because a stolen signatory key can't spend alone: it still needs the clan majority and an Afribit oversight key. A signatory whose phone is stolen should tell the clan, and the clan moves to a new wallet generation.
  - iPhones can clear website storage, so signatories install the app to the home screen, and backup words are mandatory.
  - Test on the pilot group's actual phones ([Corbado PRF notes](https://www.corbado.com/blog/passkeys-prf-webauthn)).
- **Roster substitution:**
  - A malicious server could try to give a phone the wrong public keys at setup. The wallet code comparison between signatories catches that.
  - Phones then save the wallet and check every later payment against it.
- **Oversight device:**
  - It must not run the Clans web app.
  - For now: a software key in a separate Windows account on an existing laptop, used with the Afribit oversight tool. Ledger later (see "Afribit oversight in practice").
  - Sparrow and Liana are not assumed to support this wallet type.
- **Oversight upload without a session:**
  - The oversight route accepts uploads from anyone, rate-limited. It stores only signatures by an oversight key on the exact payment, after checking each signature.
  - So the route can't be used to add approval, or to wipe a good approval with a forged one.
- **Key registration without re-authentication:**
  - Registering a signing key doesn't ask for the passkey again. Someone who steals a session could swap that signatory's key before activation.
  - The phone catches this: before confirming, it checks that its own key is in the wallet.
- **Privacy:**
  - Each wallet now has its own unspendable key, so wallets don't share a visible marker.
  - The block explorer we query sees our addresses until we run our own.
- **Mainnet** is the default network (`CLANS_CLAN_WALLET_NETWORK=bitcoin`). The server refuses to start if an oversight key is made for another network. It uses account path `87'/0'/0'` (coin type 0) and `xpub` keys, and every key in a wallet must be made for its network. A local trial with real sats ran on 6 Nov 2026 ([mainnet.md](mainnet.md)). The Phase 3 review is still to come, so keep amounts small until then.

## Communities

Afribit is the first of possibly many communities. Each community runs its own clans and approves their payouts with its own 1 to 3 oversight laptops, using the same app and kit. A clan joins a community with its join code when it's created; without one it's Afribit's. Each laptop sees only its own community's clans, and the server accepts an oversight signature only from the keys in that clan's wallet. Only the operator adds communities and laptops, as the database owner. See [communities.md](communities.md).

## Open decisions for the owner

1. Which two Afribit people do oversight? Each sets up one of the two existing laptops with the [setup guide](oversight-laptop-setup.md).
2. Before mainnet: whether to move the oversight keys to Ledgers, based on how much the clans will hold.
3. Later: whether to add the automatic co-signer for small payouts, and its limit and delay.

## Related notes

Two uncommitted research notes from earlier on 4 November cover the same ground: `docs/clans-wallet-independent-architecture-2026-11-04.md` and `docs/lightning-community-treasury-research-2026-11-04.md`. This plan follows their main conclusion: a watch-only Clans coordinating an on-chain multisig, with signers holding their own keys. It changes three things:

1. Signing happens inside the Clans app instead of separate wallet apps.
2. An oversight key protects against a compromised server.
3. A time-locked recovery path is added.

Earlier feasibility work listed this "multisig reserve" family of options. This plan picks it.
