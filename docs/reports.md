# Reports on clans and usage

**For:** the Clans operator and community oversight people.
**Code:** `backend/src/clans/reports.py`, `backend/src/clans/activity_catalog.py`

Reports are built from records the app already keeps, so there's no second copy of member data:

- **The activity log** (`audit_events`) records every action in a clan, with who did it and when. `activity_catalog.py` gives each kind of event a title and a category: `clan`, `members`, `grants`, `money`, `wallet`, `security` or `account`.
- **Sign-ins** come from login sessions.
- **Money** comes from grants, debts, the clan ledger and balances.

## For a community: from the oversight laptop

`GET /api/oversight/report?from=2026-11-01&to=2026-12-01` with the laptop's token returns that community's clans only. Add `&format=csv` for a spreadsheet. The fields are described in [clan-wallet-api.md](clan-wallet-api.md#get-apioversightreportfromyyyy-mm-ddtoyyyy-mm-ddformatjsoncsv).

## For the operator: on the server

Run as the web or database-owner environment, with the server's settings loaded:

```
python -m clans.reports summary --from 2026-11-01 --to 2026-12-01            # every community, JSON
python -m clans.reports summary --from 2026-11-01 --to 2026-12-01 --csv      # as CSV
python -m clans.reports summary --from 2026-11-01 --to 2026-12-01 --community default
python -m clans.reports events  --from 2026-11-01 --to 2026-12-01 > events.jsonl
```

`events` writes one line per event: time, clan id, a member pseudonym, event, title, category and amount. The pseudonym is the same for a member within a deployment, so you can count active and returning members, but it isn't their account id. It's derived from the session secret, so rotating that secret changes every pseudonym.

## Grants owed in KES

A grant asked for in KES is owed in KES (see [user-journeys.md](user-journeys.md#journey-5-repaying-including-with-cash)). The report keeps the sats columns for every grant and adds three KES columns that cover KES grants only:

- `paid_kes`: the KES owed on KES grants paid out in the period.
- `repaid_kes`: the KES counted from repayments in the period, at the rate when each repayment was first seen.
- `outstanding_kes`: the KES still owed on KES grants paid out so far.

`repayment_rate` is the share of paid-out grants already repaid, weighted by each grant's sats. For a KES grant its share is measured in KES, so a change in the Bitcoin price doesn't change it. For a sats grant it's measured in sats.

## Useful questions to ask

| Question | Where |
|---|---|
| How many clans are active this month? | `summary`: clans with `active_members` > 0 |
| Are members coming back? | `events`: distinct `member` per week |
| How long does a grant take from request to payment? | `events`: time from `grant_requested` to `grant_disbursed` per grant |
| Which step slows grants down? | `events`: gaps between `grant_accepted`, `payout_built`, `payout_signed`, `payout_oversight_signed`, `payout_broadcast` |
| Are grants repaid? | `summary`: `repayment_rate`, `outstanding_sats`, and `paid_kes`, `repaid_kes`, `outstanding_kes` for KES grants |
| Is any clan in trouble? | `summary`: `security` in `by_category`, and the oversight alarms |

## What's deliberately left out

- **Member names, phone numbers and addresses.** Reports name clans, never members.
- **Screen-by-screen tracking.** The app doesn't record which screens people open. If that's wanted later, it should be counts only, opt-in, and never include anything typed.
