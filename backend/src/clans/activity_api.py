"""Member-only monthly history with bounded, stable pagination."""

import base64
import json
import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException, Query, Request
from sqlalchemy import and_, or_, select

from clans import activity_catalog as catalog
from clans.models import AuditEvent, User


def install(app, security):
    from clans.live_app import membership

    @app.get("/api/clans/{clan_id}/activity")
    def history(
        clan_id: str,
        request: Request,
        month: str = Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
        timezone: str = Query(default="UTC", max_length=64),
        cursor: str | None = Query(default=None, max_length=700),
        limit: int = Query(default=25, ge=1, le=50),
    ):
        try:
            zone = ZoneInfo(timezone)
            year, number = map(int, month.split("-"))
            if not 2000 <= year <= 2100:
                raise ValueError
            start = datetime(year, number, 1, tzinfo=zone).astimezone(UTC).isoformat()
            end = (
                datetime(year + (number == 12), number % 12 + 1, 1, tzinfo=zone)
                .astimezone(UTC)
                .isoformat()
            )
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise HTTPException(422, "Choose a valid month and time zone.") from exc
        with security.db() as db:
            user = security.current(request, db)
            security.limit(request, "activity:" + user.id, 120, 60)
            membership(db, clan_id, user.id)
            query = (
                select(AuditEvent, User.display_name)
                .join(User, User.id == AuditEvent.actor_id)
                .where(
                    AuditEvent.clan_id == clan_id,
                    AuditEvent.occurred_at >= start,
                    AuditEvent.occurred_at < end,
                )
            )
            if cursor:
                try:
                    value = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
                    if value[:3] != [clan_id, month, timezone] or len(value) != 5:
                        raise ValueError
                    at, event_id = value[3:]
                    if (
                        not isinstance(at, str)
                        or not isinstance(event_id, str)
                        or not re.fullmatch(r"[a-f0-9-]{36}", event_id)
                    ):
                        raise ValueError
                    datetime.fromisoformat(at)
                except (ValueError, TypeError, KeyError, UnicodeError) as exc:
                    raise HTTPException(400, "Open this month again to load its history.") from exc
                query = query.where(
                    or_(
                        AuditEvent.occurred_at < at,
                        and_(AuditEvent.occurred_at == at, AuditEvent.id < event_id),
                    )
                )
            rows = db.execute(
                query.order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc()).limit(limit + 1)
            ).all()
            more = len(rows) > limit
            rows = rows[:limit]
            next_cursor = None
            if more:
                last = rows[-1][0]
                next_cursor = (
                    base64.urlsafe_b64encode(
                        json.dumps([clan_id, month, timezone, last.occurred_at, last.id]).encode()
                    )
                    .decode()
                    .rstrip("=")
                )
            return {
                "month": month,
                "timezone": timezone,
                "items": [
                    {
                        "id": row.id,
                        "event": row.event_type,
                        "actor": name,
                        "at": row.occurred_at,
                        **catalog.summary(row.event_type, row.payload, name),
                        "data": {
                            k: v
                            for k, v in row.payload.items()
                            if k in {"amount_sats", "amount_msat", "recovery_msat"}
                        },
                    }
                    for row, name in rows
                ],
                "next_cursor": next_cursor,
            }

    @app.get("/api/clans/{clan_id}/activity/{event_id}")
    def event_detail(clan_id: str, event_id: str, request: Request):
        """One event explained: what happened, a few safe facts, and what it relates to."""
        if not re.fullmatch(r"[a-f0-9-]{36}", event_id):
            raise HTTPException(404, "This activity isn't in your clan.")
        with security.db() as db:
            user = security.current(request, db)
            security.limit(request, "activity:" + user.id, 120, 60)
            membership(db, clan_id, user.id)
            row = db.execute(
                select(AuditEvent, User.display_name)
                .join(User, User.id == AuditEvent.actor_id)
                .where(AuditEvent.id == event_id, AuditEvent.clan_id == clan_id)
            ).first()
            if not row:
                raise HTTPException(404, "This activity isn't in your clan.")
            event, name = row
            return {
                "id": event.id,
                "event": event.event_type,
                "actor": name,
                "at": event.occurred_at,
                **catalog.summary(event.event_type, event.payload, name),
                "details": catalog.details(event.event_type, event.payload),
                "links": catalog.links(event.payload),
            }
