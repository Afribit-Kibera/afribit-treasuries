"""Alarms about clan wallets, for the clan's members and for Afribit's oversight laptops.

The chain watcher records an alarm once per cause (see `wallet_payments.alarm`). A phone
that computed a different wallet code is recorded by the web app as an audit event, so the
web app never needs to write alarms. Both are listed here.

Members see the alarms that concern their money. Afribit also sees operational ones, such
as a refresh that couldn't be built. Nothing here changes money; it only reports.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from clans.models import AuditEvent, Clan
from clans.wallet_models import ClanWalletRecord, WalletAlarm

# kind -> (shown to members, plain-English message)
ALARMS = {
    "unapproved_spend": (
        True,
        "Money left the clan wallet without an approved payout. Afribit is looking into it. "
        "Don't approve anything until Afribit has explained it.",
    ),
    "wallet_code_mismatch": (
        True,
        "A signatory's phone computed a different wallet code. Don't use this wallet until "
        "Afribit has checked it.",
    ),
    "invalid_signature": (
        True,
        "A signature didn't match the payment and was set aside. The payment wasn't sent with it.",
    ),
    "address_mismatch": (
        True,
        "An address stored on the server doesn't match the clan wallet. It isn't used.",
    ),
    "recovery_path_open": (
        True,
        "A coin has been in the clan wallet for the full recovery wait, so the signatories "
        "could move it without Afribit. Clans should have refreshed it first.",
    ),
    "receipt_reorg": (
        True,
        "A payment the clan had counted has disappeared from the blockchain.",
    ),
    "payout_reorg": (
        True,
        "A payout that had confirmed has disappeared from the blockchain.",
    ),
    "payout_accounting": (
        False,
        "A payout confirmed but couldn't be booked in the clan's records.",
    ),
    "sweep_blocked": (
        False,
        "A refresh or move couldn't be built, usually because network fees are above the limit.",
    ),
}
RECENT_DAYS = 30
UNKNOWN = (True, "Something unusual happened in the clan wallet. Afribit has been told.")


def _view(kind, *, alarm_id, reference, clan_id, generation, created_at, detail):
    members, message = ALARMS.get(kind, UNKNOWN)
    return {
        "id": alarm_id,
        "kind": kind,
        # What the alarm is about: usually a transaction id, or the wallet's id.
        "reference": reference,
        "clan_id": clan_id,
        "generation": generation,
        "created_at": created_at,
        "members": members,
        "message": message,
        "detail": detail,
    }


def alarm_views(db, *, clan_id=None, clan_ids=None, since=None, members_only=False, limit=100):
    """Alarms, newest first. `since` is an ISO time; only later alarms are returned."""
    query = select(WalletAlarm, ClanWalletRecord).join(
        ClanWalletRecord, ClanWalletRecord.id == WalletAlarm.wallet_id
    )
    if clan_id:
        query = query.where(ClanWalletRecord.clan_id == clan_id)
    if clan_ids is not None:  # one community's clans, as a subquery
        query = query.where(ClanWalletRecord.clan_id.in_(clan_ids))
    if since:
        query = query.where(WalletAlarm.created_at > since)
    rows = db.execute(query.order_by(WalletAlarm.created_at.desc()).limit(limit)).all()
    views = [
        _view(
            alarm.kind,
            alarm_id=alarm.id,
            reference=alarm.reference,
            clan_id=record.clan_id,
            generation=record.generation,
            created_at=alarm.created_at,
            detail=dict(alarm.detail or {}),
        )
        for alarm, record in rows
    ]
    events = select(AuditEvent).where(AuditEvent.event_type == "wallet_code_mismatch")
    if clan_id:
        events = events.where(AuditEvent.clan_id == clan_id)
    if clan_ids is not None:
        events = events.where(AuditEvent.clan_id.in_(clan_ids))
    if since:
        events = events.where(AuditEvent.occurred_at > since)
    for event in db.scalars(events.order_by(AuditEvent.occurred_at.desc()).limit(limit)):
        payload = dict(event.payload or {})
        wallet = db.get(ClanWalletRecord, payload.get("wallet_id"))
        views.append(
            _view(
                "wallet_code_mismatch",
                alarm_id=event.id,
                reference=payload.get("wallet_id"),
                clan_id=event.clan_id,
                generation=wallet.generation if wallet else None,
                created_at=event.occurred_at,
                # The phone's code is the useful part; the server's own code is in the view.
                detail={"signer_id": event.actor_id, "phone_code": payload.get("phone_code")},
            )
        )
    if members_only:
        views = [view for view in views if view["members"]]
    views.sort(key=lambda view: view["created_at"], reverse=True)
    return views[:limit]


def recent_count(db, clan_id) -> int:
    """Member alarms in the last 30 days, for the wallet card."""
    since = (datetime.now(UTC) - timedelta(days=RECENT_DAYS)).isoformat()
    return len(alarm_views(db, clan_id=clan_id, since=since, members_only=True))


def with_clan_names(db, views):
    names = {}
    for view in views:
        if view["clan_id"] not in names:
            clan = db.get(Clan, view["clan_id"])
            names[view["clan_id"]] = clan.name if clan else None
        view["clan_name"] = names[view["clan_id"]]
    return views
