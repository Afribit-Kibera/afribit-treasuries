# Setting up an Afribit oversight laptop

**For:** the Afribit staff who approve clan payouts, and the oversight people of any other community on Clans (see [communities.md](communities.md)). Wherever this guide says Afribit, read your own community.
**Plan:** [multisig-treasury-plan-2026-11-04.md](multisig-treasury-plan-2026-11-04.md)

Every clan payout needs one Afribit oversight signature as well as the clan majority. This guide sets up an existing Windows laptop to give that signature. No extra hardware is needed. A Ledger can replace the software key later.

Each oversight person sets up their own laptop and their own key. Never copy one key to two laptops.

## What keeps the key safe

- The key is in a separate Windows account that never opens the Clans app, email or ordinary browsing.
- The 12 backup words are stored only encrypted, with your passphrase. They're decrypted in memory only while you sign.
- The tool checks every payout against **its own records**, not the Clans server: the clan's wallet, beneficiary addresses confirmed by phone, grants already paid, and its own fee limit.
- **Remaining risk:** if malware takes over the oversight account while you type your passphrase, it could sign. It would still need the clan majority. That's why the oversight account stays clean, and why we'll move to Ledgers before larger amounts.

## 1. Create a separate Windows account

1. **Settings → Accounts → Other users → Add account.**
2. Choose "I don't have this person's sign-in information", then "Add a user without a Microsoft account".
3. Name it `Afribit Oversight` and give it a strong password that you don't use anywhere else.
4. Leave it a **Standard** account, not an administrator.

Use this account only for oversight. Don't use it for email, browsing, developer tools, AI agents or browser extensions. On a development laptop this matters most, because the development account runs a lot of downloaded code.

## 2. Turn on disk encryption

1. In your normal account, open **Settings → Privacy & security → Device encryption** (or **BitLocker** in Control Panel on Windows 11 Pro).
2. Turn it on.
3. Write down the recovery key and keep it away from the laptop. Don't save it on the laptop itself.

## 3. Install the Afribit Oversight app

The installer needs no internet and no other software.

**The developer** builds the kit with `python scripts/build_oversight_kit.py`. It prints the kit's file name, for example `afribit-oversight-99ab06f806.zip`, and its SHA-256. The developer copies the zip to a USB stick and sends the SHA-256 by message, a different route from the USB stick.

**On the laptop**, in the `Afribit Oversight` account:

1. Copy the zip from the USB stick to the desktop.
2. Check it hasn't changed on the way. Open PowerShell and run `Get-FileHash $HOME\Desktop\afribit-oversight-*.zip`. Compare the result with the SHA-256 in the developer's message. If they differ, stop and ask for a new copy.
3. Right-click the zip, choose **Extract All**, then **Extract**.
4. In the extracted folder, open `Afribit Oversight` and double-click **Install Afribit Oversight**. If Windows says it protected your PC, choose **More info**, then **Run anyway**.
5. The app opens by itself when the install finishes. Next time, use the **Afribit Oversight** icon on the desktop. You can delete the zip and the extracted folder.

To update, install a newer kit the same way, but only one for a release the team has agreed on. Your key and records are kept.

### The desktop app

The desktop app replaces this console app ([oversight-desktop-app.md](oversight-desktop-app.md)). It works on mainnet and test networks. It hasn't had the external security review yet, so keep payouts small until it has.

1. **The developer** gets `Afribit-Oversight-Setup-<version>.exe` and `SHA256SUMS.txt` from the GitHub release, or from the build's artifacts in GitHub Actions. They copy the installer to a USB stick and send the SHA-256 by message.
2. **On the laptop**, in the `Afribit Oversight` account, run `Get-FileHash $HOME\Desktop\Afribit-Oversight-Setup-*.exe` and compare it with the message. If they differ, stop.
3. Double-click the installer. The app isn't signed with a certificate, so Windows says it protected your PC and names an unknown publisher. Choose **More info**, then **Run anyway**, only after the SHA-256 matched. If Windows blocks it with no **Run anyway**, Smart App Control is on: ask the team.
4. It installs for this Windows account only and needs no administrator. It uses the same key and records as the console app, so nothing is set up again.

Don't open the console app and the desktop app at the same time. The second one says the app is already open.

## 4. First start: the app sets you up

The first time the app opens, it takes you through two steps.

**Step 1: your oversight key.** Press Enter to create it. (To restore a key from its 12 backup words, type `R` first.)

1. Choose a passphrase of at least 12 characters. Four or five random words is a good choice. You'll type it each time you approve.
2. The app shows **12 backup words once**. Write them on paper, in order, with their numbers.
   - Keep the paper somewhere safe, away from the laptop.
   - Never photograph the words or type them into anything else.
   - Anyone with the words can approve payouts as you.
3. The app hides the words and asks for two of them from your paper, to make sure they're written down correctly.

**Step 2: connect to Clans.** This happens by itself. The app then saves a file on the desktop, **Send to the Clans administrator.txt**, and copies its text so you can paste it into a message. Send it to the Clans administrator, then press Enter. It holds your public keys (one for test networks, one for Bitcoin mainnet) and the laptop's connection line. Neither is secret, and neither can approve anything.

The administrator adds both to Clans: for the server's own community, in `CLANS_CLAN_WALLET_OVERSIGHT_KEYS` and `CLANS_CLAN_WALLET_OVERSIGHT_TOKEN_HASHES`; for another community, with `python -m clans.communities add-laptop …` (see [communities.md](communities.md)). Once added, the app's main screen names the community it oversees. **Keys must be added before any clan sets up its wallet.** Each clan wallet is built with the keys configured at that moment.

Until the administrator has added the laptop, the app says Clans isn't ready for this laptop yet. Press Enter later to check again.

## 5. Every time: go through everything waiting

Open the app. If anything is waiting, it goes straight through it, one step at a time, and says who to phone and what to ask. On the main screen, pressing Enter always does the first choice: go through what's waiting, or check again.

1. **Alarms first.** Read them before anything is signed. An `unapproved_spend` alarm means money left a clan wallet without going through Clans: someone may hold enough of that clan's keys. Don't approve anything for that clan until the team has found out what happened. Type `yes` to go on; anything else stops, and the alarms stay unread.
2. **New clan wallets.** For each clan whose wallet is new, the app asks you to phone one of its signatories. They read you the 8-character wallet code from their phone. If it doesn't match, the app refuses: don't approve anything for that clan, and tell the clan and the team. This happens again when a clan moves to a new wallet.
3. **New beneficiary addresses.** The first time someone is paid to an address, the app asks you to phone them. They open **their own wallet** and read you the 6 characters after the start (`tb1q` or `tb1p`) and the last 6. Type all 12 in one go; spaces don't matter. A hacked server could swap an address, and this catches it. If the characters differ, the app skips that payout.
4. **Each payout.** The app shows the clan, each beneficiary, the amount approved, what they receive after the fee, and the address. Check it matches what you know about the grant. **Typing your passphrase is your approval**; pressing Enter skips the payout and signs nothing. For large payouts (100,000 sats or more by default), the app first asks you to type the total amount. The app sends your approval, and Clans sends the payment within a minute.

The app refuses to approve, and says why, when:

- an address hasn't been confirmed by phone, or a clan's wallet isn't registered;
- the amounts in the payment differ from the grants listed;
- change goes anywhere other than the clan's own wallet;
- the fee is above this laptop's limit (5,000 sats by default);
- a grant was already paid in a different payment.

Don't work around a refusal. Check with the clan and the team.

**Moves and refreshes** have no beneficiary. The app shows "No beneficiary: the clan's money stays in the clan's own wallets":

- A **move** sends everything in a clan's old wallet to its new one.
- A **refresh** sends the clan's oldest coins back to the same wallet, so the 6-month recovery wait starts again.

The app works out the destination from its own copy of the clan's wallets. It refuses a move or refresh that pays anywhere else, or that has a fee above this laptop's limit for moves (10,000 sats by default).

A higher-fee version of a payment you already approved is allowed, because it spends the same coins and only one version can ever confirm.

The app's other choices:

- **Clan address for funding**: the address the community sends a clan's grant money to, worked out from this laptop's own copy of the clan's wallet, so a hacked server can't swap it. On the sending wallet, check the 6 characters after the start and the last 6 match what the app shows.
- **Recent alarms**, **This laptop's records**, and **What to send the Clans administrator**.

## Commands, for administrators

The app covers everyday work. The same tool also has commands, for administrators and for working without a connection. Run them in PowerShell:

```powershell
& "$env:LOCALAPPDATA\Programs\Afribit Oversight\python\python.exe" -I -m clans.oversight <command>
```

| Command | Does |
|---|---|
| `review payout.json`, `sign payout.json --out signed.json`, `upload signed.json` | Check and sign a payout without a connection. `payout.json` is the `GET /api/clans/{clan_id}/wallet/payouts/{payout_id}` response. Upload later from a connected laptop |
| `add-wallet --clan <clan id> wallet.json` | Register a clan wallet from its `GET /api/clans/{clan_id}/wallet` response, without a connection |
| `confirm-address --name "Amina" tb1q...` | Confirm an address by phone before a payout arrives |
| `show-key` | Prints your public key. Add `--network bitcoin` for the mainnet key (a laptop set up before mainnet support gets one the next time you type the passphrase) |
| `clan-address --clan <clan id>` | The clan address to send Afribit grant funding to, worked out from the registered wallet. Use only this, never an address shown elsewhere |
| `export-backup --clan <clan id> --out backup.json` | Writes the clan's public wallet backup from the registered wallet. Give it to signatories who lost theirs. See the [recovery guide](clan-wallet-recovery.md) |
| `alarms` | Shows alarms about every clan's wallets raised since you last read them, and marks them read. `alarms --all` shows the latest 200, read or not |
| `status` | Lists registered wallets, confirmed addresses and recent signatures |
| `set-limits --max-fee 5000 --max-sweep-fee 10000 --large-payout 100000` | Changes this laptop's fee limits (for grants, and for moves and refreshes) and the amount that needs typing in full |

## If something goes wrong

| Situation | What to do |
|---|---|
| Laptop lost or broken | The key file is encrypted, so the laptop alone can't sign. Ask the administrator to remove the laptop's token line. Set up another laptop, and in the app choose **Restore my key from my 12 backup words**. Send the new connection line to the administrator. The app asks you to register the clan wallets again |
| Passphrase forgotten | Delete `oversight-key.json` from the data folder, then restore from the 12 words with a new passphrase, as above |
| Backup words may have been seen | Tell the team. Create a new key, update the server setting, and move each clan to a new wallet generation |
| The tool refuses a payout you expected to be fine | Don't work around it. Read the message, and check with the clan and the team |
| Both oversight keys lost, with no backup words | Clans can still recover their money after about 6 months, with the recovery path ([recovery guide](clan-wallet-recovery.md)) |

The data folder is `%LOCALAPPDATA%\AfribitOversight` in the oversight account. It holds the encrypted key, the laptop's records and `server.json` with the read token. Don't copy `server.json` anywhere. Copy `register.json` to a USB stick now and then. If it's lost, you'll need to register wallets and confirm addresses again.

## For developers: test the kit end to end

`scripts/e2e_oversight.py` installs a kit into a throwaway Windows profile and drives the app through a real Windows console, against a private signet in Docker and a local Clans server. It covers install, key setup (reading the backup words off the screen), the wallet code, the address check, the passphrase approval, the payment confirming on chain, and the funding address. The docstring has the two `docker run` lines for the signet.

```powershell
python scripts/build_oversight_kit.py
python scripts/e2e_oversight.py --kit .local/afribit-oversight-<commit>.zip
```

Without `--kit`, it runs the app from the checkout. The signatories sign in Python with the same algorithm as the phones. The phone code itself is covered by the browser checks.
