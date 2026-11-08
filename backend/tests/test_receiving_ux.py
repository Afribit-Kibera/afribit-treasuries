"""Receiving quotes and provider labels never change settlement authority."""

import secrets
import time
from decimal import Decimal

from test_live_app import clan, join, signup
from test_live_app import live as live
from test_money import money as money

from clans.display_rates import DisplayRate
from clans.live_models import IncomingPayment


def test_deposit_quote_retry_limits_and_member_binding(money, monkeypatch):
    app, worker, network = money
    owner, _, uid, _ = signup(app, "Deposit Owner")
    cid = clan(owner)
    uid = owner.get("/api/session").json()["user"]["id"]
    member, *_ = signup(app, "Another Member")
    join(owner, member, cid, signer=False)
    rate = DisplayRate("KES", Decimal("10000000"), int(time.time()))
    monkeypatch.setattr(app.state.security.display_rates, "get", lambda currency: rate)
    quote = owner.post(
        f"/api/clans/{cid}/deposit-quote", json={"currency": "KES", "amount": "10.01"}
    ).json()
    endpoint = f"/api/clans/{cid}/deposits"
    key = {"Idempotency-Key": secrets.token_hex(16)}
    body = {"quote": quote["quote"]}
    assert member.post(endpoint, json=body, headers=key).status_code == 400
    assert owner.post(endpoint, json={**body, "amount_sats": 100}, headers=key).status_code == 422
    first = owner.post(endpoint, json=body, headers=key)
    assert first.status_code == 200, first.text
    with app.state.security.db() as db:
        incoming = db.get(IncomingPayment, first.json()["request_id"])
        assert incoming.amount_sats == 101
        assert incoming.user_id == uid
    monkeypatch.setattr("clans.display_rates.time.time", lambda: rate.published_at + 400)
    assert owner.post(endpoint, json=body, headers=key).json() == first.json()
    assert (
        owner.post(
            endpoint, json=body, headers={"Idempotency-Key": secrets.token_hex(16)}
        ).status_code
        == 409
    )
    monkeypatch.undo()
    worker.tick()
    provider_invoice = next(iter(network.invoices.values()))
    assert provider_invoice["metadata"]["itemDesc"].endswith(" - Add money")
    view = owner.get(endpoint + "/" + first.json()["request_id"]).json()
    assert view["status"] == "pending" and view["credited_sats"] == 0
    # A forged checkout return cannot credit a clan.
    assert owner.get(f"/api/clans/{cid}").json()["balance_msat"] == "0"
    network.paid = True
    worker.tick()
    worker.tick()
    assert owner.get(endpoint + "/" + view["id"]).json()["status"] == "settled"
    assert owner.get(f"/api/clans/{cid}").json()["balance_msat"] == "101000"
    assert network.create_calls == 1


def test_provider_return_is_fixed_to_app_origin(money):
    app, worker, network = money
    captured = []
    original = worker.provider.request

    def request(method, path, **kwargs):
        if method == "POST":
            captured.append(kwargs["body"])
        return original(method, path, **kwargs)

    worker.provider.request = request
    worker.provider.create_invoice(
        "request-id", 100, description="My clan · Repayment", clan_id="clan-id"
    )
    body = captured[0]
    assert body["metadata"]["itemDesc"] == "My clan · Repayment"
    assert (
        body["checkout"]["redirectURL"]
        == app.state.security.settings.public_origin + "/?payment=request-id&clan=clan-id"
    )
    assert body["checkout"]["redirectAutomatically"] is True
