"""Community reports: usage, grants and repayments per clan, with no member names."""

import json
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from test_clan_wallet_payments import (
    address,
    clan,
    keys,
    oversight_laptop,
    sent_payout,
    tick,
)
from test_live_app import ORIGIN

from clans import oversight, reports

__all__ = ["clan", "keys"]  # pytest fixtures


def period():
    today = datetime.now(UTC).date()
    return str(today), str(today + timedelta(days=1))


def repaid_grant(clan, repay_sats):
    gid, payout = sent_payout(clan)
    clan["chain"].mine(payout["txid"])
    tick(clan)
    owner = clan["signers"][0]
    where = address(owner, clan["cid"], "repayment", gid)["address"]
    clan["chain"].mine(clan["chain"].pay(where, repay_sats))
    tick(clan)
    return gid


def laptop_client(clan, tmp_path):
    home, _ = oversight_laptop(clan, tmp_path)
    digest = oversight.connect(home, ORIGIN)
    clan["app"].state.security.settings.clan_wallet_oversight_token_hashes = digest
    token = json.loads((home / oversight.SERVER_FILE).read_text(encoding="utf-8"))["token"]
    return TestClient(clan["app"], base_url=ORIGIN, headers={"Authorization": "Bearer " + token})


def test_the_oversight_laptop_reports_on_its_clans(clan, tmp_path):
    repaid_grant(clan, 10_000)
    laptop = laptop_client(clan, tmp_path)
    start, end = period()
    route = f"/api/oversight/report?from={start}&to={end}"
    response = laptop.get(route)
    assert response.status_code == 200, response.text
    data = response.json()
    (row,) = data["clans"]
    assert row["clan_id"] == clan["cid"]
    assert (row["members"], row["signatories"]) == (4, 3)
    assert row["wallet"] == "active"
    assert row["grants_requested"] == row["grants_paid"] == 1
    assert row["paid_sats"] == 40_000
    assert row["repaid_sats"] == 10_000
    assert row["outstanding_sats"] == 30_000
    assert row["repayment_rate"] == 0.25
    assert row["money_in_sats"] == 110_000  # the 100,000 deposit and the repayment
    assert row["active_members"] >= 3 and row["sign_ins"] >= 4
    assert row["by_category"]["money"] >= 1 and row["by_category"]["grants"] >= 1
    assert data["totals"]["clans"] == 1 and data["totals"]["paid_sats"] == 40_000
    # Reports name clans, never members.
    for name in ("Organizer", "Second Signer", "Third Signer", "Plain Member"):
        assert name not in response.text

    sheet = laptop.get(route + "&format=csv")
    assert sheet.status_code == 200
    assert sheet.text.splitlines()[0].startswith("clan_id,clan,community")
    assert clan["cid"] in sheet.text

    assert laptop.get(f"/api/oversight/report?from={end}&to={start}").status_code == 422
    assert laptop.get("/api/oversight/report?from=2026-01-01&to=2028-01-01").status_code == 422
    anonymous = TestClient(clan["app"], base_url=ORIGIN)
    assert anonymous.get(route).status_code == 401
    # A member's own session is not an oversight laptop.
    assert clan["signers"][0].get(route).status_code == 401


def test_the_event_file_uses_pseudonyms(clan):
    repaid_grant(clan, 5_000)
    start, end = period()
    with clan["app"].state.security.db() as db:
        first = list(reports.events(db, "secret-one", start, end))
        again = list(reports.events(db, "secret-one", start, end))
        other = list(reports.events(db, "secret-two", start, end))
        user_ids = {row[0] for row in db.execute(reports.select(reports.Membership.user_id)).all()}
    assert first == again and len(first) > 10
    assert {e["member"] for e in first}.isdisjoint(e["member"] for e in other)
    assert not user_ids.intersection(e["member"] for e in first)
    assert all(e["title"] != "Clan activity" for e in first)
    paid = [e for e in first if e["event"] == "grant_disbursed"]
    assert paid and paid[0]["amount_sats"] == 40_000 and paid[0]["category"] == "money"
