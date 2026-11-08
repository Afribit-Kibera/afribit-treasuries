"""Local audit regressions; no expected failures may mask dispatch defects.

Only disposable test databases and the existing MockTransport payment provider
are used. Database-tampering cases model a compromised database writer, not an
unauthenticated HTTP client. See the security assessment for that prerequisite.
"""

import secrets

import pytest
from pydantic import SecretStr
from sqlalchemy import select
from test_live_app import clan, signup
from test_live_app import live as live
from test_money import approve, funded, prepared
from test_money import money as money

from clans.live_models import PaymentIntent
from clans.money_models import Balance, Debt, DispatchAuthorization, Payout, WorkerStatus
from clans.treasury_provider import ProviderError
from clans.treasury_worker import TreasuryWorker


@pytest.mark.parametrize("amount", [0, -1, True, 1.5, "1000", 10_000_001])
def test_security_deposit_requires_bounded_integer_sats(money, amount):
    app, _, network = money
    owner, _, _, _ = signup(app)
    cid = clan(owner)
    response = owner.post(
        f"/api/clans/{cid}/deposits",
        json={"amount_sats": amount},
        headers={"Idempotency-Key": secrets.token_hex(16)},
    )
    assert response.status_code == 422
    assert network.create_calls == 0


def test_security_nonmember_cannot_read_or_fund_another_clan(money):
    app, _, _ = money
    _, _, cid, request_id = funded(money)
    outsider, _, _, _ = signup(app, "Unrelated account")
    assert outsider.get(f"/api/clans/{cid}").status_code == 403
    assert outsider.get(f"/api/clans/{cid}/deposits/{request_id}").status_code == 403
    assert (
        outsider.post(
            f"/api/clans/{cid}/deposits",
            json={"amount_sats": 100},
            headers={"Idempotency-Key": secrets.token_hex(16)},
        ).status_code
        == 403
    )


def test_security_idempotency_key_cannot_change_deposit_amount(money):
    app, _, _ = money
    owner, _, _, _ = signup(app)
    cid = clan(owner)
    headers = {"Idempotency-Key": secrets.token_hex(16)}
    path = f"/api/clans/{cid}/deposits"
    first = owner.post(path, json={"amount_sats": 100}, headers=headers)
    assert first.status_code == 200
    repeated = owner.post(path, json={"amount_sats": 100}, headers=headers)
    assert repeated.status_code == 200
    assert repeated.json() == first.json()
    assert owner.post(path, json={"amount_sats": 101}, headers=headers).status_code == 409


def test_security_unbalanced_ledger_blocks_approved_dispatch(money):
    app, worker, network = money
    _, _, a, key_a, b, key_b, cid, _, prefix, _ = prepared(money)
    approve(a, key_a, prefix)
    approve(b, key_b, prefix)
    with app.state.security.db() as db:
        db.get(Balance, cid).balance_msat += 1
    worker.tick()
    assert network.pay_calls == 0
    with app.state.security.db() as db:
        assert db.get(WorkerStatus, "treasury").status == "unavailable"


@pytest.mark.parametrize("status", ["queued", "sending", "uncertain"])
def test_security_database_state_cannot_dispatch_without_signatures(money, status):
    app, worker, network = money
    _, _, _, _, _, _, _, gid, _, payment_hash = prepared(money)
    # The legitimate beneficiary has prepared an invoice, but nobody has signed it.
    # Model the database-write authority held by the provisioned web database owner.
    with app.state.security.db() as db:
        intent = db.scalar(select(PaymentIntent).where(PaymentIntent.grant_id == gid))
        db.add(
            Payout(
                intent_id=intent.id,
                requested_by=intent.canonical["beneficiary_id"],
                payment_hash=payment_hash,
                amount_msat=intent.canonical["amount_msat"],
                fee_limit_msat=intent.canonical["fee_limit_msat"],
                status=status,
            )
        )
    worker.tick()
    assert network.pay_calls == 0, "Unsigned payout was sent by the mocked treasury provider"


def queued(money):
    data = prepared(money)
    approve(data[2], data[3], data[8])
    approve(data[4], data[5], data[8])
    return data


def test_send_commit_without_provider_record_never_retries(money, monkeypatch):
    app, worker, network = money
    data = queued(money)
    sent = []

    def interrupted(*args):
        sent.append(args)
        raise ProviderError("Response lost before provider record was observable")

    monkeypatch.setattr(worker.provider, "send", interrupted)
    worker.tick()
    worker.tick()
    assert len(sent) == 1
    assert network.pay_calls == 0
    with app.state.security.db() as db:
        assert db.scalar(select(Payout)).status == "uncertain"
        assert db.get(Balance, data[6]).reserved_msat == 101000
        assert db.get(Debt, data[7]) is None
        assert db.scalar(select(DispatchAuthorization)) is not None


def test_interrupted_success_reconciles_after_key_revocation_and_disabled_sends(money):
    app, worker, network = money
    data = queued(money)
    network.pending_send = True
    worker.tick()
    from clans.live_models import Passkey

    with app.state.security.db() as db:
        for key in db.scalars(select(Passkey)).all():
            key.active = False
    worker.settings = worker.settings.model_copy(update={"payouts_enabled": False})
    network.outgoing[data[9]]["status"] = "Complete"
    worker.tick()
    worker.tick()
    assert network.pay_calls == 1
    with app.state.security.db() as db:
        assert db.get(Debt, data[7]).outstanding_msat == 100000
        assert db.get(Balance, data[6]).reserved_msat == 0


@pytest.mark.parametrize("field", ["authentication_tag", "amount_msat", "payment_hash"])
def test_tampered_dispatch_authorization_is_not_settled_or_resent(money, field):
    app, worker, network = money
    data = queued(money)
    network.pending_send = True
    worker.tick()
    with app.state.security.db() as db:
        record = db.scalar(select(DispatchAuthorization))
        setattr(record, field, 123000 if field == "amount_msat" else "0" * 64)
    network.outgoing[data[9]]["status"] = "Complete"
    worker.tick()
    assert network.pay_calls == 1
    with app.state.security.db() as db:
        assert db.get(Debt, data[7]) is None
        assert db.get(Balance, data[6]).reserved_msat == 101000
        assert db.get(WorkerStatus, "treasury").status == "unavailable"


@pytest.mark.parametrize("scope", ["global", "clan"])
def test_24h_budget_includes_maximum_fee_and_blocks_dispatch(money, scope):
    app, worker, network = money
    data = queued(money)
    worker.settings = worker.settings.model_copy(update={f"payout_{scope}_24h_sats": 100})
    worker.tick()
    assert network.pay_calls == 0
    with app.state.security.db() as db:
        assert db.scalar(select(DispatchAuthorization)) is None
        assert db.get(Balance, data[6]).reserved_msat == 101000
        assert db.get(WorkerStatus, "treasury").status == "ready"


def test_terminal_failure_releases_reservation_but_not_spending_budget(money):
    app, worker, network = money
    data = queued(money)
    network.pending_send = True
    worker.tick()
    network.outgoing[data[9]].update(status="Failed")
    worker.tick()
    with app.state.security.db() as db:
        assert db.scalar(select(Payout)).status == "failed"
        assert db.get(Balance, data[6]).reserved_msat == 0
        assert db.scalar(select(DispatchAuthorization)) is not None


def test_payment_hash_mismatch_cannot_release_uncertain_funds(money):
    app, worker, network = money
    data = queued(money)
    network.pending_send = True
    worker.tick()
    network.outgoing[data[9]].update(status="Failed", paymentHash="0" * 64)
    worker.tick()
    with app.state.security.db() as db:
        assert db.get(Balance, data[6]).reserved_msat == 101000
        assert db.get(WorkerStatus, "treasury").status == "unavailable"


@pytest.mark.parametrize(
    "update",
    [
        {"dispatch_secret": SecretStr("")},
        {"dispatch_secret": SecretStr("short")},
        {"payout_global_24h_sats": 0},
        {"payout_clan_24h_sats": 0},
        {"payout_clan_24h_sats": 10001},
    ],
)
def test_worker_requires_independent_key_and_explicit_budgets(money, update):
    _, worker, _ = money
    with pytest.raises(ValueError):
        TreasuryWorker(worker.settings.model_copy(update=update), provider=worker.provider)


def test_worker_dispatch_secret_cannot_be_session_secret(money):
    _, worker, _ = money
    settings = worker.settings.model_copy(
        update={"dispatch_secret": worker.settings.session_secret}
    )
    with pytest.raises(ValueError):
        TreasuryWorker(settings, provider=worker.provider)


def test_worker_dispatch_secret_cannot_be_provider_key(money):
    _, worker, _ = money
    secret = SecretStr("provider-credential-" * 4)
    settings = worker.settings.model_copy(
        update={"dispatch_secret": secret, "btcpay_api_key": secret}
    )
    with pytest.raises(ValueError):
        TreasuryWorker(settings, provider=worker.provider)


def test_web_production_refuses_owner_database_role(money):
    app, _, _ = money
    from clans.live_app import create_app

    settings = app.state.security.settings.model_copy(
        update={
            "environment": "production",
            "database_url": SecretStr("postgresql+psycopg://afribit_clans@127.0.0.1/afribit_clans"),
        }
    )
    with pytest.raises(ValueError, match="runtime role"):
        create_app(settings)


def test_web_production_refuses_worker_dispatch_key(money):
    app, _, _ = money
    from clans.live_app import create_app

    settings = app.state.security.settings.model_copy(
        update={
            "environment": "production",
            "database_url": SecretStr(
                "postgresql+psycopg://afribit_clans_web@127.0.0.1/afribit_clans"
            ),
            "dispatch_secret": SecretStr("worker-only-" * 8),
        }
    )
    with pytest.raises(ValueError, match="dispatch secrets"):
        create_app(settings)


def test_existing_budget_charge_blocks_second_authorization(money):
    app, worker, network = money
    data = queued(money)
    worker.tick()
    from clans.dispatch_security import authorize

    with app.state.security.db() as db:
        payout = db.scalar(select(Payout))
        intent = db.get(PaymentIntent, payout.intent_id)
        from clans.live_models import Grant

        grant = db.get(Grant, intent.grant_id)
        settings = worker.settings.model_copy(
            update={"payout_global_24h_sats": 201, "payout_clan_24h_sats": 201}
        )
        with pytest.raises(ProviderError, match="budget exhausted"):
            authorize(db, settings, payout, intent, grant)
    assert network.pay_calls == 1
    with app.state.security.db() as db:
        assert db.get(Debt, data[7]) is not None


@pytest.mark.parametrize("currency", ["SATS", "KES"])
def test_postgres_concurrent_clans_share_one_global_budget(money, monkeypatch, currency):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from clans import treasury_worker

    app, worker, network = money
    if app.state.security.engine.dialect.name != "postgresql":
        pytest.skip("Requires isolated PostgreSQL transaction locks")
    first = prepared(money)
    network.paid = False
    payments = [first, prepared(money)]
    for data in payments:
        approve(data[2], data[3], data[8])
        approve(data[4], data[5], data[8])
    worker.settings = worker.settings.model_copy(
        update={"payout_global_24h_sats": 150, "payout_clan_24h_sats": 150}
    )
    if currency == "KES":
        from test_fiat_limits import kes_worker

        kes_worker(
            worker, monkeypatch, payout_global_24h_kes=15, payout_clan_24h_kes=15, max_payout_kes=15
        )
    gate = Barrier(2)
    authorize = treasury_worker.authorize

    def simultaneous_authorization(*args):
        gate.wait(timeout=10)
        return authorize(*args)

    monkeypatch.setattr(treasury_worker, "authorize", simultaneous_authorization)
    with app.state.security.db() as db:
        ids = list(db.scalars(select(Payout.id)).all())
    assert len(ids) == 2

    def send(payout_id):
        try:
            worker.payout(payout_id)
            return "sent"
        except ProviderError as exc:
            assert "budget exhausted" in str(exc)
            return "blocked"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(send, ids))
    assert sorted(outcomes) == ["blocked", "sent"]
    assert network.pay_calls == 1
    with app.state.security.db() as db:
        records = list(db.scalars(select(DispatchAuthorization)).all())
        assert len(records) == 1
        assert records[0].amount_msat + records[0].fee_limit_msat == 101000
        assert sorted(db.get(Balance, data[6]).reserved_msat for data in payments) == [0, 101000]


def test_relabeling_dispatched_payout_as_queued_does_not_resend(money):
    app, worker, network = money
    queued(money)
    network.pending_send = True
    worker.tick()
    with app.state.security.db() as db:
        payout = db.scalar(select(Payout))
        payment_hash = payout.payment_hash
        payout.status, payout.attempts, payout.dispatched_at = "queued", 0, None
    network.outgoing.pop(payment_hash)
    worker.tick()
    assert network.pay_calls == 1
    with app.state.security.db() as db:
        assert db.scalar(select(Payout)).status == "uncertain"


def test_expiry_does_not_release_authorized_reservation(money):
    app, worker, network = money
    data = queued(money)
    network.pending_send = True
    worker.tick()
    with app.state.security.db() as db:
        intent = db.scalar(select(PaymentIntent))
        intent.expires_at = "2000-01-01T00:00:00+00:00"
    worker.expire()
    with app.state.security.db() as db:
        assert db.get(Balance, data[6]).reserved_msat == 101000


def test_disabling_receiving_still_reconciles_existing_invoice(money):
    app, worker, network = money
    owner, _, _, _ = signup(app)
    cid = clan(owner)
    result = owner.post(
        f"/api/clans/{cid}/deposits",
        json={"amount_sats": 1000},
        headers={"Idempotency-Key": secrets.token_hex(16)},
    )
    assert result.status_code == 200
    worker.tick()
    assert network.create_calls == 1
    worker.settings = worker.settings.model_copy(update={"receiving_enabled": False})
    network.paid = True
    worker.tick()
    with app.state.security.db() as db:
        assert db.get(Balance, cid).balance_msat == 1000000
    assert network.create_calls == 1
