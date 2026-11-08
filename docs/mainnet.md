# Clan wallets on Bitcoin mainnet

Bitcoin mainnet is the default network. The Phase 3 external review
([multisig-treasury-plan-2026-11-04.md](multisig-treasury-plan-2026-11-04.md)) hasn't happened
yet, so keep amounts small until it has. This page covers the settings and what the real-sats
trial on 6 Nov 2026 showed.

## The settings

```
CLANS_CLAN_WALLET_NETWORK=bitcoin         # the default; signet or testnet4 to try it out
CLANS_CLAN_WALLET_OVERSIGHT_KEYS=[fingerprint/87'/0'/0']xpub...
CLANS_CLAN_WALLET_CONFIRMATIONS=3         # deposits count after this many blocks
CLANS_CLAN_WALLET_ESPLORA_URL=            # optional; see Block explorers below
```

- **Keys.** Mainnet keys use account path `87'/0'/0'` and are written as `xpub`. Test-network
  keys use `87'/1'/0'` and `tpub`. The server refuses a wallet with any key from the wrong
  network, and refuses to start if an oversight key doesn't match the network.
- **Phones.** Phones make the key for the wallet's network from the same 12 words. A signatory's
  test-network and mainnet keys come from the same words but are different keys.
- **Oversight laptop.** It holds both public keys. `show-key --network bitcoin` prints the mainnet
  one. A laptop set up before mainnet support gets its mainnet key the next time its passphrase
  is typed.
- **Addresses.** Clan addresses start with `bc1p`. Payout addresses must start with `bc1q` or
  `bc1p`. The laptop asks for the characters after `bc1q` (or `bc1p`), so the beginning every
  address shares isn't read back.

## Block explorers

The chain watcher reads the chain from Esplora APIs. List them in
`CLANS_CLAN_WALLET_ESPLORA_URL`, comma separated. It uses the first that answers, moves to the
next when one fails, and tries the first again after 10 minutes. Left empty, it uses
mempool.space and then blockstream.info for the network.

Any Esplora API works:

- **Your own node.** electrs, or the mempool app on an Umbrel or Start9
  (`http://umbrel.local:3006/api`). Put it first. No rate limits, and nobody else sees which
  addresses are the clans'. If the server isn't on the same network, reach it over a VPN such as
  Tailscale rather than opening a port.
- **Public ones.** `https://mempool.space/api`, `https://blockstream.info/api`, or another public
  mempool instance such as `https://mempool.emzy.de/api`. They rate-limit, and they see the
  clans' addresses.

Each cycle (every 30 seconds) reads only the chain tip. A wallet is read in full when a new
block arrives, when something changes for it (a new address, a payout request, a signature), or
every `CLANS_CLAN_WALLET_IDLE_READ_SECONDS` (5 minutes by default). So a payment with no block
yet shows within 5 minutes. A fully signed payout is sent on the next cycle.

The recovery tool takes the same kind of list: `--esplora url1,url2`.

## Real-sats trial, 6 Nov 2026

The trial ran locally on mainnet: the app on this PC, Postgres in Docker, and blockstream.info
for chain data, because mempool.space wasn't reachable. Three members each used a separate
browser profile with a passkey and their own signing key. The oversight laptop app ran in its own
profile. The grant beneficiary used a separate single-key wallet to receive the payout and repay.

Scripts:

- `scripts/mainnet_trial.py` runs the steps.
- `scripts/trial_members.py` drives each member's phone screens.
- `scripts/trial_beneficiary.py` is the beneficiary's own wallet.

Words and passphrases are kept in plain text under `.local/mainnet-trial/secrets`. Delete that
folder once the money is back with its funder.

```
python scripts/mainnet_trial.py laptop | serve | members | keys
TRIAL_DEPOSIT=6075 python scripts/mainnet_trial.py deposit    # shows the QR code
python scripts/mainnet_trial.py funded
python scripts/mainnet_trial.py grant kiosk | sign kiosk | approve kiosk | sent kiosk
python scripts/mainnet_trial.py repay | activity
TRIAL_RETURN_ADDRESS=bc1q... python scripts/mainnet_trial.py grant return | sign return | approve return | sent return
```

### Bugs it found (fixed)

1. **The server refused every mainnet payout address.** It only accepted `tb1` addresses.
   Covered by `test_mainnet_grants_are_paid_to_mainnet_addresses`.
2. **Phones refused to sign mainnet payouts with "Your key changed".** After the PIN, the payout
   screen worked out the phone's key the test-network way. Restoring a signing key on a new phone
   had the same bug. `publicSigningKey` now requires the network, so a call that leaves it out
   no longer compiles.

3. **Public block explorers rate-limit the chain watcher.**
   - **The load.** Each 30-second cycle makes about 10 requests per clan wallet: the tip, fee estimates, each used address and each transaction. That's about 1,200 an hour for one clan.
   - **What happened.** Blockstream allows 700 an hour without an API key, and refused the trial's watcher after a few hours. mempool.space has similar public limits.
   - **The fix in code.** The watcher waits longer after each failed cycle, up to 10 minutes. It now reads a quiet wallet only on a new block or every 5 minutes, and moves to another explorer when one refuses ([Block explorers](#block-explorers)).
   - **For production.** Use your own Esplora node first in `CLANS_CLAN_WALLET_ESPLORA_URL`, with public ones after it.

### Smaller findings

- **Laptop rate limit.** The laptop app is allowed 120 server checks an hour. Pressing "Check
  again" every few seconds uses them up. The trial script now waits a minute between checks.
- **The fee rate was rounded up to a whole sat/vB** (fixed). An estimate of 1.01 sat/vB became 2,
  so a payout paid about twice the fee it needed. Rates are now kept to a thousandth.
- **The beneficiary's fee preview assumes the payout spends one coin.** The return payout spent
  two: the deposit's change and the repayment. Its fee was 739 sats, not the 452 shown, so
  the funder received 3,986 sats, not "about 4,273". Signatories and the laptop saw the exact
  figures before signing. Fixed: payouts now spend the largest coins first, and the preview
  counts the coins that takes.
- **Partial repayment works as designed.** Juma's wallet paid its own network fee, so he repaid
  2,180 of the 2,530 sats. The grant shows "in recovery" with 350 sats still owed.
- **Another explorer can stand in.** Blockstream refused the trial for hours. Restarting the
  server with `TRIAL_ESPLORA=https://mempool.emzy.de/api` picked up where it left off.
- **The Activity screen still says "Clan updated"** for wallet events. The server now titles
  every event; the screen change is frontend job F12.

### Results

| Step | Result |
|---|---|
| Deposit | 6,075 sats (KES 600), confirmed; home screen showed KES 600.62 |
| Grant request, votes, terms | KES 250 = 2,530 sats; 2 votes for; accepted |
| Payout | Phones and laptop signed; 2,302 sats received, 228 sats fee |
| Repayment | Juma's wallet sent everything it held: 2,180 sats credited, 350 still owed, grant "in recovery" |
| Activity | Every step recorded; wallet events still titled "Clan updated" on screen (F12) |
| Return grant | 4,725 sats voted to the funder's address; 2 coins spent, 739 sats fee, 3,986 received (block 974,813) |
| Left in the clan | 1,000 sats, the buffer kept for the fee, which comes back as change |
| Report | `python -m clans.reports summary`: 8,255 in, 7,255 paid out, 2,180 repaid, balance 1,000 |
