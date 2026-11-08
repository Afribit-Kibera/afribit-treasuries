# Who uses Clans, and how

**For:** anyone deciding whether their group should use Clans, the people who will run it, and the people building it.
**Status:** describes the app as built on 6 November 2026, tested on the Bitcoin test network and with real sats on mainnet. Production mainnet waits for an external security review ([mainnet.md](mainnet.md)).

## Clans in one paragraph

A **clan** is a small group that pools money in its own Bitcoin wallet and lends or grants it to its members. A **community** is the wider group that the clans belong to and that keeps watch over them: Afribit in Kibera, but equally a family, a school, a church or a traders' association. Each payment out of a clan needs a majority of the clan's chosen signatories **and** one approval from the community's oversight. Signatories hold their keys on their own phones, and the community holds its key on an offline-minded laptop. The Clans server only sees public keys, so neither Afribit nor any one person can move a clan's money alone.

## The people

| Role | Who it is | What they do in Clans |
|---|---|---|
| **Operator** | Afribit Africa, which runs the Clans server | Adds communities and their oversight laptops. Reads platform reports. Never holds clan money or keys. |
| **Community oversight** | 1 to 3 trusted people chosen by the community | Keep an oversight laptop. Approve payouts after checking them by phone. Read the community's reports and alarms. |
| **Organizer** | The person who starts a clan | Creates the clan with the community's join code. Chooses the rules and the signatories. Invites members. |
| **Signatory** | Usually 3 members the clan trusts | Keep a signing key on their phone. Check and sign each payout. Compare the wallet code when the wallet starts. |
| **Member** | Everyone in the clan | Vote on grant requests. Ask for grants. Pay money in. See the clan's activity. |
| **Beneficiary** | A member whose grant passed | Accepts the terms. Gives an address from their own Bitcoin wallet. Repays. |
| **Cash agent** | An OTC trader or shop outside the app | Turns a member's cash into bitcoin and sends it to the clan's address. |

## What a community can be

The roles stay the same; only the people change.

| Community | Who holds oversight | Its clans | What the money is for |
|---|---|---|---|
| **Afribit Kibera** | Afribit staff | Savings groups of traders and families in Kibera | Kiosk stock, school fees, emergencies |
| **A family** | One or two elders, or a trusted relative abroad | Each household or branch of the family | School fees, medical bills, a family business, funerals |
| **A school** | The board treasurer and the head teacher | Parents of each class or year | Fee loans between terms, uniforms, trips |
| **A church or mosque** | Two elected officials | Fellowship or youth groups | Welfare, member businesses |
| **A traders' association** | The association's officials | Groups of stall-holders in a market | Stock, rent, repairs |

The community doesn't take part in each clan's vote. Its job is to be the second pair of eyes: is this payment going to the member the clan voted for, for the amount they approved?

## Journey 1: a community joins Clans

*Example: a school decides that parents of each class should run their own fee-loan clan, overseen by the board.*

1. **The board chooses its oversight people.** It picks 1 to 3 people. Each needs a Windows laptop with a separate Windows account kept only for oversight ([oversight-laptop-setup.md](oversight-laptop-setup.md)).
2. **Afribit creates the community.** This gives the school its **join code**, which is shown once.
3. **Each oversight person sets up their laptop.** The install kit works without internet. The guided app makes the oversight key, shows its 12 backup words to write down, and protects the key with a passphrase. It then saves a file for Afribit with the laptop's public key and connection line.
4. **Afribit adds each laptop** to the community. The laptop now says "Oversight for <School>. Nothing is waiting for you."
5. **The board gives the join code to each class organizer.**

From now on, every clan made with that code is overseen by the school's laptops and by no one else's.

## Journey 2: a clan starts

*Example: Amina organizes "Kibera Real Sats" with Juma and Wanjiru.*

1. **Sign up.** Each person opens the app on their phone, chooses a username and makes a **passkey**, so there's no password to forget or steal. They write down 12 words that let them back into their account if they lose the phone.
2. **Create the clan.** Amina types the community's join code (or leaves it empty for Afribit), names the clan, and sets the rules: how many votes a grant needs, and how many signatories the clan has.
3. **Invite.** Amina sends each person a private invitation link, marked as a signatory role where it should be. They accept, and the custody terms explain who holds what.
4. **Make signing keys.** Each signatory makes a **signing key** on their phone. The phone shows 12 backup words, which they write down, then protects the key with a 6-digit PIN or the phone's passkey. The key never leaves the phone.
5. **Compare the wallet code.** Once every key is in, each phone works out the clan wallet from the keys and shows an 8-character **wallet code**. The signatories read their codes to each other, and to the oversight person when asked. If the codes match, everyone sees the same wallet and nobody slipped in a key. The wallet becomes active.
6. **Save the backup file.** Each signatory saves the wallet backup file. With it and enough signatories' words, the clan can get its money back even if Clans and the community disappear, after a long waiting period ([clan-wallet-recovery.md](clan-wallet-recovery.md)).

In the trial, all three phones and the oversight laptop agreed on code `4meznqqq`.

## Journey 3: money comes in

1. A member taps **Add money**, says what it's for and how much, and gets a QR code and address. The phone checks that the address really belongs to the clan wallet before showing it.
2. They pay from any Bitcoin wallet, or hand cash to an agent who pays it (Journey 5).
3. The app sees the payment within about a minute and shows it as waiting. It counts after it confirms on the network (3 blocks in production, about 30 minutes).
4. The home screen shows the clan's available money in sats and in KES.

## Journey 4: a grant, from request to payment

*Example from the mainnet trial: Juma asks for KES 250 for kiosk stock.*

1. **Ask.** Juma taps **Receive grant**, types KES 250 and the purpose. The app turns it into sats at today's rate (2,530 sats) and fixes that amount. The clan pays out 2,530 sats, and Juma owes KES 250 (Journey 5).
2. **Vote.** The other members see the request under Activity and on Home, and vote. A beneficiary can't vote on their own grant. Amina and Wanjiru voted yes.
3. **Accept the terms.** Juma accepts the grant and agrees to repay it.
4. **Give a receiving address.** Juma pastes an address from his own wallet, for example Blink, Phoenix or a hardware wallet. The app shows what he'll receive after the network fee (2,302 sats) before he confirms. The fee comes out of the grant, so the clan never pays more than it voted for.
5. **Signatories check and sign.** Each signatory opens the payment. Their phone independently checks that it pays exactly Juma's address, exactly the approved amount, and sends any change back to the clan, then they sign with their PIN. A signatory can't sign a payment to themselves.
6. **Oversight approves.** The oversight laptop lists the payment. The guided app has the oversight person phone Juma and read back characters of his address from his own wallet, so a hacked server can't swap the address. It then shows the amounts, and approves with the passphrase.
7. **Sent and confirmed.** The payment goes out and confirms. Juma's wallet received 2,302 sats. Activity shows "Grant paid".

If a payment waits too long because fees rose, Clans prepares a higher-fee version for the same people to sign again.

## Journey 5: repaying, including with cash

1. **Open the grant and tap "Repay this grant".** The grant shows what's still owed, for example "KES 250.00 (about 2,530 sats at today's rate)".
2. **Pay from a wallet.** The member enters an amount in sats and gets a QR code for that grant's own repayment address.
3. **Or pay cash through an agent.** The member taps **Pay cash through an agent** and types the KES they're handing over. It starts at what's still owed and can be less. The phone shows about how many sats that is at today's rate, and says the agent's own rate may differ. It then shows a large QR and the address, with a copy button, after checking that the address belongs to the clan wallet. The agent can send any amount. The screen checks every 10 seconds and shows:
   - "Waiting for the agent's payment." The member should stay with the agent.
   - "Payment seen: 2,500 sats." This usually takes a minute or two. The member can now leave.
   - "Confirmed: KES 247.10 counted towards your grant. KES 2.90 still owed."

   If today's rate can't be loaded, the QR still shows, without the sats guide.
4. **Partial payments are fine.** Every payment to that grant's address counts towards it, whoever sends it, and lowers what's still owed. Anything beyond the debt is kept as clan money and recorded as surplus.
5. **A grant asked for in KES is owed in KES.** Juma asked for KES 250, so he owes KES 250, whatever the Bitcoin price does. Each repayment counts in KES at the rate when the clan wallet first saw it. The rate and the KES counted are kept with the payment, and Activity shows both. If no fresh rate is available, the payment waits and counts as soon as one is. Less than KES 1 left counts as repaid.
6. **A grant asked for in sats is owed in sats,** as before. So are grants made before KES debts existed.

The sender pays the network fee. When fees are high, many small repayments cost more, so clans should agree on a sensible minimum.

## Journey 6: seeing what happened

- **Activity** lists everything in the clan, month by month, with a plain title: "Added a signing key", "Compared the wallet code", "Signed a payment", "Oversight approved a payment", "Grant paid", "Money received".
- **Each item opens a page** explaining what it means and why it matters, with safe facts (amounts, fees, key fingerprints) and links to the grant, the payment and the transaction on a block explorer. It never shows addresses or anyone's private details.
- **Members see only their own clan.**

## Journey 7: when something goes wrong

| Situation | What happens |
|---|---|
| A signatory loses their phone | They restore their signing key on a new phone from their 12 words. If the words are lost too, the clan starts a new wallet version and moves the money across. |
| A signatory leaves | The clan starts a new wallet version with the new signatories. Everyone compares the new code. The old wallet's money is moved across with the usual signatures. |
| A phone sees a different wallet code | The wallet must not be used. An alarm goes to the community's oversight. |
| Money leaves without a payout Clans prepared | An alarm goes to members and oversight. |
| A payment is stuck | A higher-fee version is prepared to sign. |
| The community's oversight stops approving, or Clans shuts down | After the recovery waiting period, the signatories can move the money themselves, with the backup file. Clans normally refreshes coins before that time is up. |

## Journey 8: reports

- **The community** gets a report for any period from its oversight laptop: one row per clan with members, how many were active, sign-ins, grants requested and paid, money in, repayments, what's still owed and the repayment rate, in sats and, for KES grants, in KES. It's available as a table (CSV) for spreadsheets. It names clans, never members.
- **Afribit as operator** gets the same report across all communities, and the activity log as a file for analysis, where each member is a pseudonym. Both are run on the server ([reports.md](reports.md)).

## Not built yet

- **SMS alerts** for votes, payments waiting and alarms.
- **Paying in over Lightning.** A swap service would turn a Lightning payment into an on-chain payment to the clan, so the clan stays non-custodial.
- **The desktop app for oversight** replaces the guided console app. It's built and works on mainnet ([oversight-desktop-app.md](oversight-desktop-app.md)). Its report screen and record backup aren't built yet.
- **Hardware wallets as oversight signers.** A Ledger could sign once that's built and tested. A Trezor can't sign a clan wallet.
- **Production on mainnet,** after the external security review.
