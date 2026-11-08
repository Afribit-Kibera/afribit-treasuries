# Communities: other groups running their own clans

**For:** the Clans operator, and the people who lead a community that wants to use Clans.
**Code:** `backend/src/clans/communities.py`

Afribit is the first community. A **community** is any group, like Afribit, that runs its own set of clans and approves their payouts with its own oversight laptops. Each community's laptops see and approve only that community's clans.

## How it works

- Every clan belongs to one community. A clan made without a community code belongs to Afribit.
- A clan wallet needs the clan's signatories **and** one approval from its community's oversight laptop. A community has 1 to 3 oversight laptops, and any one of them can approve.
- Members see the community's name in the app: "Waiting for Kibera Savers", "Phone Kibera Savers", and so on.
- An oversight laptop only lists its own community's clans, payouts and alarms. It can't approve another community's payout: the server refuses the signature, because it isn't from one of that clan's keys.
- Every clan wallet keeps the oversight keys it was built with. Adding or removing a laptop changes only wallets made afterwards.
- Only the operator changes communities, from the server, as the database owner. The web app can read communities but never change them, so a hacked web server can't swap a community's oversight keys.

Afribit's own keys and laptops stay in the server settings (`CLANS_CLAN_WALLET_OVERSIGHT_KEYS`, `..._TOKEN_HASHES`), as before. Its name comes from `CLANS_CLAN_DEFAULT_COMMUNITY_NAME` (default `Afribit`).

## Onboarding a community

Do these in order. **The laptop must be added before any of the community's clans makes its wallet**: until then, the app tells the organizer that the community hasn't set up an oversight laptop yet.

1. **Agree who runs oversight.** The community picks 1 to 3 people. Each needs a Windows laptop with its own Windows account for oversight, as in [oversight-laptop-setup.md](oversight-laptop-setup.md).
2. **Create the community** on the server, as the database owner:

   ```
   python -m clans.communities create --name "Kibera Savers"
   ```

   It prints the community's short name (`kibera-savers`) and its **join code**, for example `HQ7M-4XPA`. The code is shown once: send it to the community's leaders. It isn't a password, but share it only with organizers you expect, because anyone with it can make a clan that the community's laptops will see.
3. **Set up each laptop** with the same kit as Afribit, following [oversight-laptop-setup.md](oversight-laptop-setup.md). Each laptop saves **Send to the Clans administrator.txt** on its desktop. The person sends that file to the operator.
4. **Add each laptop** with the two lines from its file:

   ```
   python -m clans.communities add-laptop kibera-savers --oversight-key "[fp/87'/0'/0']xpub..." --token-hash <connection line>
   ```

   Once added, opening the app on that laptop shows "Oversight for Kibera Savers." and "Nothing is waiting for you." A key or a laptop can belong to only one community.
5. **Organizers make clans.** In the app, on the first step of **Create a clan**, they type the join code in **Community code**. Spaces, dashes and letter case don't matter. A wrong or old code is refused. Leaving it empty puts the clan under Afribit.

## Day to day

The community's oversight people do exactly what Afribit's do: phone a signatory for each new wallet's code, phone each new beneficiary for their address characters, and approve payouts with their passphrase. The app tells them who to phone and what to type.

## Changing a community

All through `python -m clans.communities …` on the server, with the database owner's settings:

| Command | Does |
|---|---|
| `list` | Every community, its laptops and how many clans it has |
| `new-code kibera-savers` | A new join code. The old one stops working. Existing clans aren't affected |
| `close kibera-savers` | Stops new clans joining. Its clans and laptops keep working |
| `reopen kibera-savers` | Lets new clans join again |
| `add-laptop kibera-savers --oversight-key … --token-hash …` | Adds a laptop (at most 3) |
| `remove-laptop kibera-savers --token-hash …` | Disconnects a laptop: it can no longer list payouts |
| `remove-laptop kibera-savers --oversight-key … --force` | Takes a key out of new wallets. Without `--force` it's refused once clan wallets use the key |

**A lost or stolen laptop.** Remove its connection line at once. Its key is still in the wallets that were built with it, and a thief would also need the passphrase and the clan's signatures. Then remove the key with `--force`, add a replacement laptop, and move each of the community's clans to a new wallet, the same way as when a phone is lost.

## Not built yet

- Communities can't yet manage themselves from a web screen. The operator runs the commands above.
- Payout limits and alarm messages are the same for every community.
- SMS alerts to a community's oversight people.
