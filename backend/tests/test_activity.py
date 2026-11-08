"""Monthly history boundaries, membership and stable paging."""

from sqlalchemy import delete
from test_live_app import clan, signup
from test_live_app import live as live

from clans.models import AuditEvent


def test_months_are_local_and_pages_do_not_repeat(live):
    owner, _, uid, _ = signup(live, "History Owner")
    cid = clan(owner)
    uid = owner.get("/api/session").json()["user"]["id"]
    other, *_ = signup(live, "Not a member")
    endpoint = f"/api/clans/{cid}/activity"
    with live.state.security.db() as db:
        db.execute(delete(AuditEvent).where(AuditEvent.clan_id == cid))
        for i in range(60):
            db.add(
                AuditEvent(
                    clan_id=cid,
                    actor_id=uid,
                    event_type="deposit_requested",
                    occurred_at="2026-10-31T21:30:00+00:00",
                    payload={"amount_sats": i, "private_value": "hidden"},
                )
            )
        db.add(
            AuditEvent(
                clan_id=cid,
                actor_id=uid,
                event_type="clan_created",
                occurred_at="2026-10-31T20:59:59+00:00",
            )
        )
        db.add(
            AuditEvent(
                clan_id=cid,
                actor_id=uid,
                event_type="clan_created",
                occurred_at="2026-11-30T21:00:00+00:00",
            )
        )
    params = {"month": "2026-11", "timezone": "Africa/Nairobi"}
    assert other.get(endpoint, params=params).status_code == 403
    assert owner.get(endpoint, params={**params, "limit": 51}).status_code == 422
    first = owner.get(endpoint, params=params)
    assert first.status_code == 200, first.text
    data = first.json()
    assert len(data["items"]) == 25 and data["next_cursor"]
    assert all("private_value" not in row["data"] for row in data["items"])
    ids = {row["id"] for row in data["items"]}
    while data["next_cursor"]:
        data = owner.get(endpoint, params={**params, "cursor": data["next_cursor"]}).json()
        assert not ids.intersection(row["id"] for row in data["items"])
        ids.update(row["id"] for row in data["items"])
    assert len(ids) == 60
    assert (
        owner.get(endpoint, params={"month": "2026-10", "timezone": "Africa/Nairobi"}).json()[
            "items"
        ][0]["at"]
        == "2026-10-31T20:59:59+00:00"
    )
    assert owner.get(endpoint, params={**params, "cursor": "not-valid"}).status_code == 400
    assert owner.get(endpoint, params={**params, "timezone": "Bad/Zone"}).status_code == 422
    assert owner.get(endpoint, params={**params, "month": "2026-13"}).status_code == 422
    assert (
        owner.get(
            endpoint, params={**params, "month": "2026-12", "cursor": first.json()["next_cursor"]}
        ).status_code
        == 400
    )
    assert owner.get(f"/api/clans/{cid}?include_activity=false").json()["activity"] == []
    assert owner.get(f"/api/clans/{cid}?include_activity=false").json()["journal"] == []


def test_every_event_is_explained_without_private_details(live):
    owner, *_ = signup(live, "Detail Owner")
    cid = clan(owner)
    uid = owner.get("/api/session").json()["user"]["id"]
    other, *_ = signup(live, "Detail Outsider")
    other_cid = clan(other)
    with live.state.security.db() as db:
        key = AuditEvent(
            clan_id=cid,
            actor_id=uid,
            event_type="wallet_key_registered",
            occurred_at="2026-11-06T09:00:00+00:00",
            payload={"wallet_id": "w", "fingerprint": "24edf488", "replaced": False},
        )
        paid = AuditEvent(
            clan_id=cid,
            actor_id=uid,
            event_type="payout_address_given",
            occurred_at="2026-11-06T09:01:00+00:00",
            payload={"grant_id": "g" * 36, "address": "bc1qprivate", "amount_sats": 2530},
        )
        alarm = AuditEvent(
            clan_id=cid,
            actor_id=uid,
            event_type="wallet_alarm_unexpected_spend",
            occurred_at="2026-11-06T09:02:00+00:00",
            payload={"reference": "r", "txid": "a" * 64},
        )
        db.add_all([key, paid, alarm])
        db.flush()
        ids = key.id, paid.id, alarm.id
    month = {"month": "2026-11", "timezone": "Africa/Nairobi"}
    items = {
        row["id"]: row
        for row in owner.get(f"/api/clans/{cid}/activity", params=month).json()["items"]
    }
    assert items[ids[0]]["title"] == "Added a signing key"
    assert items[ids[0]]["category"] == "wallet"
    assert "Detail Owner made a signing key" in items[ids[0]]["summary"]
    assert items[ids[2]]["title"] == "Wallet alarm"
    assert all(row["title"] != "Clan activity" for row in items.values())

    detail = owner.get(f"/api/clans/{cid}/activity/{ids[1]}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["title"] == "Gave a receiving address"
    assert body["details"] == [{"label": "Amount", "value": "2,530 sats"}]
    assert body["links"] == {"grant_id": "g" * 36}
    assert "bc1qprivate" not in detail.text
    assert owner.get(f"/api/clans/{cid}/activity/{ids[2]}").json()["links"] == {"txid": "a" * 64}
    # Only members of the event's own clan can open it.
    assert other.get(f"/api/clans/{cid}/activity/{ids[0]}").status_code == 403
    assert other.get(f"/api/clans/{other_cid}/activity/{ids[0]}").status_code == 404
    assert owner.get(f"/api/clans/{cid}/activity/not-an-id").status_code == 404


def test_every_recorded_event_has_a_title():
    """A new event type must be added to the catalog, or it shows as plain 'Clan activity'."""
    import pathlib
    import re as _re

    from clans import activity_catalog

    source = "\n".join(
        path.read_text("utf-8")
        for path in pathlib.Path(activity_catalog.__file__).parent.glob("*.py")
    )
    call = r'audit\(\s*db,\s*[^,"()]+,\s*[^,"]+?,\s*"([a-z_]+)"'
    recorded = set(_re.findall(call, source))
    recorded |= set(_re.findall(r'event_type="([a-z_]+)"', source))
    recorded -= {"test_fixture"}
    missing = sorted(e for e in recorded if e not in activity_catalog.KINDS and not e.endswith("_"))
    assert len(recorded) > 25
    assert not missing, missing
