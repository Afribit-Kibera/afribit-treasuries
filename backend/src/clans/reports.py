"""Reports on clans and how the app is used, built from records the app already keeps.

The activity log (audit_events) records every action; sign-ins come from login sessions;
money comes from the clan ledger, grants and debts. Nothing here is a new copy of member data.

A community's oversight laptop gets its own clans' report from GET /api/oversight/report.
The platform operator gets every community's report, and the activity log as a file, with
this command, run on the server:

    python -m clans.reports summary --from 2026-11-01 --to 2026-12-01 [--community ID] [--csv]
    python -m clans.reports events  --from 2026-11-01 --to 2026-12-01 > events.jsonl

Reports name clans, never members. The events file replaces each member with a stable
pseudonym, so usage can be studied without knowing who did what.
"""

import argparse
import csv
import hashlib
import hmac
import io
import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select

from clans import activity_catalog as catalog
from clans.live_models import Grant, LoginSession
from clans.models import AuditEvent, Clan, Membership
from clans.money_models import Balance, Debt
from clans.wallet_models import ClanWalletRecord

MAX_DAYS = 366
COLUMNS = (
    "clan_id",
    "clan",
    "community",
    "created_at",
    "members",
    "signatories",
    "wallet",
    "network",
    "balance_sats",
    "active_members",
    "sign_ins",
    "actions",
    "grants_requested",
    "grants_paid",
    "paid_sats",
    "paid_kes",
    "money_in_sats",
    "repaid_sats",
    "repaid_kes",
    "grants_open",
    "outstanding_sats",
    "outstanding_kes",
    "repayment_rate",
)
# KES columns count only grants whose debt is in KES. Older grants, counted in sats, are in
# the sats columns only: their KES value is never guessed.
KES_COLUMNS = ("paid_kes", "repaid_kes", "outstanding_kes")


def period(start: str, end: str) -> tuple[str, str]:
    """Dates (YYYY-MM-DD, end exclusive) as the UTC timestamps the database stores."""
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if not first < last or last - first > timedelta(days=MAX_DAYS):
        raise ValueError(f"Choose a period of 1 to {MAX_DAYS} days.")

    def stamp(day: date) -> str:
        return datetime(day.year, day.month, day.day, tzinfo=UTC).isoformat()

    return stamp(first), stamp(last)


def _msat(payload: dict, key: str) -> int:
    try:
        return int(payload.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _kes(minor: int) -> float:
    """KES cents as KES, to the cent."""
    return round(minor / 100, 2)


def repaid_share(grant, debt) -> float:
    """How much of a paid grant is repaid, from 0 to 1. KES debts are measured in KES."""
    if grant.obligation_currency == "KES":
        return 1 - grant.outstanding_minor / grant.principal_minor
    return debt.recovered_msat / debt.principal_msat


def report(db, clan_ids, start: str, end: str) -> dict:
    """One row per clan for the period, plus totals. `clan_ids` is a list or a subquery."""
    since, until = period(start, end)
    clans = db.scalars(select(Clan).where(Clan.id.in_(clan_ids)).order_by(Clan.created_at)).all()
    ids = [c.id for c in clans]
    members: dict[str, set] = defaultdict(set)
    signers: Counter = Counter()
    for m in db.scalars(
        select(Membership).where(Membership.clan_id.in_(ids), Membership.active.is_(True))
    ):
        members[m.clan_id].add(m.user_id)
        signers[m.clan_id] += bool(m.is_signer)
    every_member = set().union(*members.values()) if members else set()
    sessions = Counter(
        db.scalars(
            select(LoginSession.user_id).where(
                LoginSession.user_id.in_(every_member),
                LoginSession.created_at >= since,
                LoginSession.created_at < until,
            )
        )
    )
    wallets = {}
    for record in db.scalars(
        select(ClanWalletRecord)
        .where(ClanWalletRecord.clan_id.in_(ids))
        .order_by(ClanWalletRecord.generation)
    ):
        wallets[record.clan_id] = record  # the newest generation wins
    balances = {
        b.clan_id: b.balance_msat // 1000
        for b in db.scalars(select(Balance).where(Balance.clan_id.in_(ids)))
    }
    grants = defaultdict(list)
    for g in db.scalars(select(Grant).where(Grant.clan_id.in_(ids))):
        grants[g.clan_id].append(g)
    debts = {
        d.grant_id: d
        for d in db.scalars(
            select(Debt).where(Debt.grant_id.in_(select(Grant.id).where(Grant.clan_id.in_(ids))))
        )
    }
    events = defaultdict(list)
    for e in db.scalars(
        select(AuditEvent).where(
            AuditEvent.clan_id.in_(ids),
            AuditEvent.occurred_at >= since,
            AuditEvent.occurred_at < until,
        )
    ):
        events[e.clan_id].append(e)

    rows = []
    for clan in clans:
        mine = events[clan.id]
        people = members[clan.id]
        active = {e.actor_id for e in mine if e.actor_id in people}
        active |= {user for user in people if sessions[user]}
        paid_grants = [(g, debts[g.id]) for g in grants[clan.id] if g.id in debts]
        clan_debts = [d for _, d in paid_grants]
        principal = sum(d.principal_msat for d in clan_debts)
        # Each grant counts by the sats paid out; its repaid share is in its own currency.
        recovered = sum(d.principal_msat * repaid_share(g, d) for g, d in paid_grants)
        settled = [e.payload for e in mine if e.event_type == "treasury_settled"]
        by_id = {g.id: g for g in grants[clan.id]}
        disbursed = [
            by_id.get(e.payload.get("grant_id")) for e in mine if e.event_type == "grant_disbursed"
        ]
        wallet = wallets.get(clan.id)
        rows.append(
            {
                "clan_id": clan.id,
                "clan": clan.name,
                "community": clan.community_id or "default",
                "created_at": clan.created_at,
                "members": len(people),
                "signatories": signers[clan.id],
                "wallet": wallet.status if wallet else "none",
                "network": wallet.network if wallet else "",
                "balance_sats": balances.get(clan.id, 0),
                "active_members": len(active),
                "sign_ins": sum(sessions[user] for user in people),
                "actions": len(mine),
                "by_category": dict(Counter(catalog.kind(e.event_type).category for e in mine)),
                "grants_requested": sum(since <= g.created_at < until for g in grants[clan.id]),
                "grants_paid": sum(e.event_type == "grant_disbursed" for e in mine),
                "paid_sats": sum(
                    _msat(e.payload, "amount_msat")
                    for e in mine
                    if e.event_type == "grant_disbursed"
                )
                // 1000,
                "paid_kes": _kes(
                    sum(
                        g.principal_minor for g in disbursed if g and g.obligation_currency == "KES"
                    )
                ),
                "money_in_sats": sum(_msat(p, "amount_msat") for p in settled) // 1000,
                "repaid_sats": sum(_msat(p, "recovery_msat") for p in settled) // 1000,
                "repaid_kes": _kes(sum(_msat(p, "credited_kes_minor") for p in settled)),
                "grants_open": sum(
                    g.status not in {"recovered", "rejected", "cancelled"} for g in grants[clan.id]
                ),
                "outstanding_sats": sum(d.outstanding_msat for d in clan_debts) // 1000,
                "outstanding_kes": _kes(
                    sum(
                        g.outstanding_minor
                        for g, _ in paid_grants
                        if g.obligation_currency == "KES"
                    )
                ),
                "repayment_rate": round(recovered / principal, 3) if principal else None,
            }
        )
    totals = {
        key: sum(row[key] for row in rows)
        for key in COLUMNS
        if rows and isinstance(rows[0][key], int) and key not in {"repayment_rate"}
    }
    for key in KES_COLUMNS:
        totals[key] = round(sum(row[key] for row in rows), 2)
    totals["clans"] = len(rows)
    return {"from": start, "to": end, "clans": rows, "totals": totals}


def as_csv(data: dict) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=COLUMNS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(data["clans"])
    return out.getvalue()


def events(db, secret: str, start: str, end: str, clan_ids=None):
    """The activity log for analysis: one record per event, members as pseudonyms."""
    since, until = period(start, end)
    query = select(AuditEvent).where(
        AuditEvent.occurred_at >= since, AuditEvent.occurred_at < until
    )
    if clan_ids is not None:
        query = query.where(AuditEvent.clan_id.in_(clan_ids))
    key = hashlib.sha256(("clans-report:" + secret).encode()).digest()
    for e in db.scalars(query.order_by(AuditEvent.occurred_at, AuditEvent.id)):
        found = catalog.kind(e.event_type)
        yield {
            "at": e.occurred_at,
            "clan_id": e.clan_id,
            "member": hmac.new(key, e.actor_id.encode(), "sha256").hexdigest()[:16],
            "event": e.event_type,
            "title": found.title,
            "category": found.category,
            "amount_sats": (
                _msat(e.payload, "amount_msat") // 1000
                if "amount_msat" in e.payload
                else _msat(e.payload, "amount_sats") or None
            ),
        }


def main(argv=None) -> int:
    from clans import communities
    from clans.live_config import LiveSettings
    from clans.live_security import Security

    parser = argparse.ArgumentParser(prog="python -m clans.reports")
    parser.add_argument("what", choices=["summary", "events"])
    parser.add_argument("--from", dest="start", required=True)
    parser.add_argument("--to", dest="end", required=True)
    parser.add_argument(
        "--community", help="A community's id, or 'default' for Afribit. Leave out for all."
    )
    parser.add_argument("--csv", action="store_true", help="summary as CSV instead of JSON")
    args = parser.parse_args(argv)
    settings = LiveSettings()
    security = Security(settings)
    try:
        period(args.start, args.end)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    with security.db() as db:
        clan_ids = (
            select(Clan.id)
            if args.community is None
            else communities.in_community(None if args.community == "default" else args.community)
        )
        if args.what == "summary":
            data = report(db, clan_ids, args.start, args.end)
            print(as_csv(data) if args.csv else json.dumps(data, indent=2), end="")
        else:
            for record in events(
                db, settings.session_secret.get_secret_value(), args.start, args.end, clan_ids
            ):
                print(json.dumps(record))
    security.engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
