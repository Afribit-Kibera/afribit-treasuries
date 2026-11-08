"""Changing account access must not forgive grants or resend ambiguous payments."""

import secrets

import pytest
from sqlalchemy import select
from test_live_app import Authenticator, client
from test_live_app import live as live
from test_money import approve, prepared
from test_money import money as money

from clans.live_models import Grant
from clans.money_models import Balance, Debt, Payout


def rotate_words(who, key):
    options = who.post("/api/account/reauth/options", json={"action": "recovery_codes"}).json()
    response = who.post(
        "/api/account/reauth/verify",
        json={
            "challenge_id": options["challenge_id"],
            "credential": key.assertion(options["options"]["challenge"]),
        },
    )
    assert response.status_code == 200
    return response.json()


def restore(app, kit):
    lost, key = client(app), Authenticator()
    options = lost.post(
        "/api/auth/recover/options",
        json={
            "handle": kit["handle"],
            "code": kit["recovery_codes"][0],
        },
    ).json()
    result = lost.post(
        "/api/auth/recover/verify",
        json={
            "challenge_id": options["challenge_id"],
            "credential": key.registration(options["options"]["challenge"]),
        },
    )
    assert result.status_code == 200, result.text
    state = lost.get("/api/session").json()
    lost.headers["X-CSRF-Token"] = state["csrf"]
    return lost, state


def test_paid_grant_remains_after_new_words_and_recovery(money):
    app, worker, network = money
    owner, key, a, ka, b, kb, cid, gid, prefix, _ = prepared(money)
    account = owner.get("/api/session").json()["user"]["id"]
    approve(a, ka, prefix)
    approve(b, kb, prefix)
    worker.tick()
    kit = rotate_words(owner, key)
    with app.state.security.db() as db:
        assert db.get(Debt, gid).outstanding_msat == 100_000
    restored, state = restore(app, kit)
    assert state["user"]["id"] == account and state["clans"][0]["id"] == cid
    with app.state.security.db() as db:
        assert db.get(Grant, gid).beneficiary_id == account
        assert db.get(Debt, gid).outstanding_msat == 100_000
    second = restored.post(
        f"/api/clans/{cid}/grants",
        json={
            "purpose": "Try requesting another grant",
            "amount_sats": 100,
        },
        headers={"Idempotency-Key": secrets.token_hex(16)},
    )
    assert second.status_code == 409
    worker.tick()
    assert network.pay_calls == 1


@pytest.mark.parametrize("status", ["uncertain", "queued"])
def test_recovery_retains_dispatched_payment_and_its_reservation(money, status):
    app, worker, network = money
    owner, key, a, ka, b, kb, cid, gid, prefix, _ = prepared(money)
    kit = rotate_words(owner, key)
    approve(a, ka, prefix)
    approve(b, kb, prefix)
    network.pending_send = True
    worker.tick()
    with app.state.security.db() as db:
        db.scalar(select(Payout)).status = status
    restored, _ = restore(app, kit)
    with app.state.security.db() as db:
        assert db.get(Debt, gid) is None
        assert db.get(Balance, cid).reserved_msat == 101_000
        assert db.scalar(select(Payout)).status == status
    worker.tick()
    assert network.pay_calls == 1
    assert restored.get(f"/api/clans/{cid}").status_code == 200
