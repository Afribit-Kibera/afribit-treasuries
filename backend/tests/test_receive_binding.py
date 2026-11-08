"""No receiving attribution changes may survive provider I/O."""

import secrets

import pytest
from sqlalchemy import func, select
from test_live_app import clan, signup
from test_live_app import live as live
from test_money import approve, prepared
from test_money import money as money

from clans.live_models import IncomingPayment
from clans.money_models import Balance, Debt, DepositReceipt, ReceiveAuthorization


def request(owner, cid, **extra):
    response = owner.post(
        f"/api/clans/{cid}/deposits",
        json={"amount_sats": 40, **extra},
        headers={"Idempotency-Key": secrets.token_hex(16)},
    )
    assert response.status_code == 200, response.text
    return response.json()["request_id"]


@pytest.mark.parametrize(
    "field", ["clan_id", "user_id", "amount_sats", "provider_invoice_id", "bolt11"]
)
@pytest.mark.parametrize("during_io", [False, True])
def test_changed_receiving_identity_cannot_credit(money, monkeypatch, field, during_io):
    app, worker, network = money
    owner, *_ = signup(app)
    other, *_, state = signup(app, "Other")
    cid, other_cid = clan(owner), clan(other)
    rid = request(owner, cid)
    worker.incoming(rid)
    replacement = {
        "clan_id": other_cid,
        "user_id": state["user"]["id"],
        "amount_sats": 41,
        "provider_invoice_id": "another-invoice",
        "bolt11": "relabelled",
    }[field]

    def tamper():
        with app.state.security.db() as db:
            setattr(db.get(IncomingPayment, rid), field, replacement)

    if during_io:
        original = worker.provider.settlement

        def settlement(*args):
            result = original(*args)
            tamper()
            return result

        monkeypatch.setattr(worker.provider, "settlement", settlement)
    else:
        tamper()
    network.paid = True
    worker.incoming(rid)
    with app.state.security.db() as db:
        assert db.get(IncomingPayment, rid).status == "review_required"
        assert db.get(Balance, cid).balance_msat == 0
        assert db.get(Balance, other_cid).balance_msat == 0
        assert db.scalar(select(func.count()).select_from(DepositReceipt)) == 0


def test_repayment_cannot_be_changed_to_contribution_during_io(money, monkeypatch):
    app, worker, network = money
    owner, _, a, ka, b, kb, cid, gid, prefix, _ = prepared(money)
    approve(a, ka, prefix)
    approve(b, kb, prefix)
    worker.tick()
    rid = request(owner, cid, grant_id=gid)
    network.paid = False
    worker.incoming(rid)
    original = worker.provider.settlement

    def changed(*args):
        result = original(*args)
        with app.state.security.db() as db:
            db.get(IncomingPayment, rid).grant_id = None
        return result

    monkeypatch.setattr(worker.provider, "settlement", changed)
    network.paid = True
    worker.incoming(rid)
    with app.state.security.db() as db:
        assert db.get(IncomingPayment, rid).status == "review_required"
        assert db.get(Debt, gid).outstanding_msat == 100_000
        assert db.get(Balance, cid).balance_msat == 899877
        assert db.scalar(select(DepositReceipt).where(DepositReceipt.incoming_id == rid)) is None


def test_missing_provider_binding_is_held(money):
    app, worker, network = money
    owner, *_ = signup(app)
    cid = clan(owner)
    rid = request(owner, cid)
    worker.incoming(rid)
    invoice = next(iter(network.invoices.values()))
    invoice["metadata"]["clansReceiveAuthorization"] = "forged"
    network.paid = True
    worker.incoming(rid)
    with app.state.security.db() as db:
        assert db.get(IncomingPayment, rid).status == "review_required"
        assert db.get(Balance, cid).balance_msat == 0


def test_legacy_pending_invoice_never_gets_invented_authorization(money):
    app, worker, network = money
    owner, *_ = signup(app)
    cid = clan(owner)
    rid = request(owner, cid)
    with app.state.security.db() as db:
        db.get(IncomingPayment, rid).status = "reconciling"
    worker.incoming(rid)
    assert network.create_calls == 0
    with app.state.security.db() as db:
        assert db.get(IncomingPayment, rid).status == "review_required"
        assert db.get(ReceiveAuthorization, rid) is None
