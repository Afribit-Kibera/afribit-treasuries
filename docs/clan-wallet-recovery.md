# Recovering a clan's money without Clans or Afribit

Every clan wallet has a second way to spend, the **recovery path**. Once a coin has sat in the wallet for the recovery period (26,280 blocks, about 6 months) without being spent, the clan's signatories can move it on their own. Afribit's key isn't needed, and neither is the Clans app.

This guide is for that situation, and for rehearsing it on a test network.

Test networks only, like the wallets themselves.

## When to use it

- Clans and Afribit are both gone, or have stopped working for months.
- Afribit has refused to approve payments for a long time and the clan wants its money back.

In normal times, don't. Payments go through the app with Afribit's approval.

## How the wait works

- The wait is counted **for each coin**, from the block that confirmed it.
- Each deposit or repayment is a new coin.
- A payout's change is a new coin as well, so after a payout, the change starts its own wait.
- Coins still waiting stay in the wallet. Sweep them later, once their wait has passed.

`coins` (below) shows how long each coin has left.

Clans normally stops the wait from ever running out: about a month before a coin's wait ends, it asks the signatories and Afribit to sign a **refresh**, which sends the coin back to the same wallet. If you see a coin whose wait has passed while Clans is running, Afribit is alerted.

## If the clan moved to a new wallet

After a lost phone or a change of signatories, the clan gets a new wallet with a new backup file, and the money is moved across.

- Save the **new** backup file once the new wallet is active.
- **Keep the old one.** If anything stayed in the old wallet (the move hadn't gone out yet, or someone paid an old address later), only the old file and the old wallet's signatories' words can recover it.
- Recover each wallet separately, with its own backup file.

## What you need

| | Who has it |
|---|---|
| The **wallet backup file** (`backup.json`). It holds public keys only | Each signatory saves it from the app. Afribit can export it from an oversight laptop (`export-backup`) |
| The **12 backup words** of enough signatories: the number shown by `check` (2 of 3, 3 of 5 or 4 of 7) | Each signatory, on paper |
| A computer with Python 3.12 and the Clans backend installed (`python -m pip install ./backend` from a copy of the code) | Someone the clan trusts to run commands. They never see anyone's words |
| An address to move the money to, agreed by the signatories | The clan |

**Never type backup words into a website, a message or someone else's computer.** Each signatory signs on a computer they trust. The signing step works offline.

## Steps

### 1. Check the backup

```
python -m clans.recover check backup.json
```

The tool rebuilds the wallet from the keys in the file and refuses a file that doesn't match itself. It prints the wallet code and the first address.

- Compare the wallet code with the one in the app, or with what other signatories see from their own copies.
- Every signatory should get the same code.

### 2. See the coins

```
python -m clans.recover coins backup.json
```

The tool lists each coin, its confirmations, and either "recovery ready" or how many days are left. It reads a public block explorer (mempool.space, then blockstream.info, by default; `--esplora url1,url2` to use others, such as your own node).

It always checks all of the first 1,000 change addresses, because Clans never sends change, refreshes or moves anywhere else, so this takes a minute or two. In another wallet app, such as Sparrow, set the gap limit to 1000 to see the same coins.

### 3. Agree the destination

Choose one address to receive everything: a new clan wallet, or a wallet the signatories control together. Read it out on a call, or meet in person. Don't rely on a forwarded message alone.

### 4. Build the sweep

```
python -m clans.recover build backup.json --to <address> --fee-rate 2 --out sweep.json
```

- The sweep moves every coin whose wait has passed, minus the network fee, to the one address.
- Pick `--fee-rate` from the explorer's current fees.
- The tool refuses a fee above 10,000 sats unless you pass `--max-fee`.
- `sweep.json` holds no secrets. Send it to each signatory.

### 5. Each signatory signs

On their own computer, each signatory runs:

```
python -m clans.recover sign backup.json sweep.json --out signed-<name>.json
```

1. The tool checks the sweep, then shows the amount, the fee and the destination.
2. Type the last 6 characters of the agreed address. A different address stops here.
3. Type your 12 words. They aren't shown and aren't saved.
4. Send `signed-<name>.json` back. It holds your signature only, never your words.

The tool refuses to sign:

- a sweep for a different wallet;
- a sweep that pays anywhere but one address;
- a sweep that doesn't carry the recovery wait;
- a sweep that spends a coin outside the wallet;
- a sweep whose fee is above the limit;
- with words that aren't a signatory's. Afribit's key can't sign the recovery path.

### 6. Send it

With enough signed copies:

```
python -m clans.recover finish backup.json sweep.json signed-a.json signed-b.json --broadcast
```

Without `--broadcast`, the tool prints the finished transaction instead. You can paste it into any block explorer's "broadcast transaction" page, or into Bitcoin Core's `sendrawtransaction`.

If the network says the transaction is "non-BIP68-final", a coin's wait hasn't passed. Build the sweep again later.

## Watching the wallet in Bitcoin Core

Bitcoin Core (version 26 or later) can watch the wallet without Clans:

```
python -m clans.recover core backup.json > import.json
bitcoin-cli -signet createwallet "clan" true true
bitcoin-cli -signet -rpcwallet=clan importdescriptors "$(cat import.json)"
bitcoin-cli -signet -rpcwallet=clan getbalances
```

- The import holds public keys only, so Core can show balances and addresses but can't sign.
- Bitcoin Core can't read 12-word backups, so signatures come from `recover sign`.
- A timestamp of `0` makes Core scan the whole chain. Use the wallet's creation time to make it faster.
- Signing in Bitcoin Core with keys exported from the words is possible, but hasn't been tested yet.

## Rehearsal checklist (Phase 2)

1. Fund the pilot wallet on signet. For the rehearsal, use a wallet created with a short recovery wait (`CLANS_CLAN_WALLET_RECOVERY_BLOCKS=4320`, about 30 days, the minimum).
2. Each signatory saves the backup file from the app and checks it with `check`.
3. Once the wait has passed, build, sign and send a sweep without the app or an oversight laptop.
4. Record how long each step took, and any message that confused people.

**Lost phone and refresh (also Phase 2):**

1. One signatory pretends their phone was lost. Another signatory starts a new clan wallet from the app.
2. The "lost" signatory makes a new key on another phone. Everyone else keeps theirs. All confirm the new wallet code, and both oversight laptops register it (`add-wallet`).
3. Two signatories and Afribit sign the move. Check that the old wallet ends at 0 and the new one holds the money minus the fee.
4. Save the new backup file, and check it with `check`.
5. With the short-wait wallet, let a coin reach the refresh point and sign the refresh. Record its fee.
