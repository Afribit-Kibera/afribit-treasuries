"""Additional adversarial regression gate; all payment I/O is MockTransport."""

import secrets

from sqlalchemy import select
from test_live_app import live as live
from test_money import money as money
from test_money import prepared
from test_signer_trust import queue, trust

from clans.live_models import IncomingPayment, PaymentIntent
from clans.money_models import Balance, DispatchAuthorization, Payout, PayoutPoll, WorkerStatus
from clans.treasury_provider import ProviderError, ProviderUnavailable
from clans.treasury_worker import TreasuryWorker


def test_untrusted_clan_cannot_starve_an_independently_authorized_clan(money, tmp_path):
    app, worker, network = money
    untrusted = prepared(money)
    network.paid = False
    trusted = prepared(money)
    trust(money, trusted, tmp_path)
    queue(untrusted)
    queue(trusted)
    with app.state.security.db() as db:
        bad = db.scalar(select(Payout).where(Payout.payment_hash == untrusted[9]))
        good = db.scalar(select(Payout).where(Payout.payment_hash == trusted[9]))
        bad.created_at = "2026-01-01T00:00:00+00:00"
        good.created_at = "2026-01-02T00:00:00+00:00"
        good_id = good.id
    for _ in range(3):
        worker.tick()
    after_ticks = network.pay_calls
    with app.state.security.db() as db:
        status = db.get(WorkerStatus, "treasury").status
    # Control: the second payment is valid when processed independently.
    worker.payout(good_id)
    assert network.pay_calls == 1
    assert status == "ready"
    assert after_ticks == 1, (
        f"Valid clan starved across three cycles: sends={after_ticks}, worker={status}"
    )
    with app.state.security.db() as db:
        bad = db.scalar(select(Payout).where(Payout.payment_hash == untrusted[9]))
        assert bad.status == "queued" and bad.attempts == 0
        assert bad.last_error == "clan_verification_required"
        assert db.get(DispatchAuthorization, bad.id) is None
        assert db.get(PayoutPoll, bad.id).reason == "clan_verification_required"
        assert db.get(Balance, untrusted[6]).reserved_msat == 101000


def separate_member_addresses(monkeypatch):
    import itertools

    import test_live_app
    from fastapi.testclient import TestClient

    addresses = itertools.count(1)

    def client(app):
        return TestClient(
            app,
            base_url=test_live_app.ORIGIN,
            headers={"Origin": test_live_app.ORIGIN},
            client=(f"192.0.2.{next(addresses)}", 50000),
        )

    monkeypatch.setattr(test_live_app, "client", client)


def test_four_blocked_payments_do_not_fill_every_batch_or_block_deposits(
    money, tmp_path, monkeypatch
):
    separate_member_addresses(monkeypatch)
    app, worker, network = money
    blocked = []
    for _ in range(4):
        network.paid = False
        blocked.append(prepared(money))
    network.paid = False
    good = prepared(money)
    trust(money, good, tmp_path)
    for data in [*blocked, good]:
        queue(data)
    with app.state.security.db() as db:
        for n, data in enumerate([*blocked, good]):
            row = db.scalar(select(Payout).where(Payout.payment_hash == data[9]))
            row.created_at = f"2026-01-0{n + 1}T00:00:00+00:00"
    request = good[0].post(
        f"/api/clans/{good[6]}/deposits",
        json={"amount_sats": 40},
        headers={"Idempotency-Key": secrets.token_hex(16)},
    )
    assert request.status_code == 200
    network.paid = False
    worker.tick()
    assert network.pay_calls == 0
    network.paid = True
    worker.tick()
    assert network.pay_calls == 1
    with app.state.security.db() as db:
        assert db.get(IncomingPayment, request.json()["request_id"]).status == "settled"
        assert db.get(WorkerStatus, "treasury").status == "ready"
        for data in blocked:
            row = db.scalar(select(Payout).where(Payout.payment_hash == data[9]))
            assert db.get(PayoutPoll, row.id).reason == "clan_verification_required"


def test_deferred_schedule_survives_restart_and_expiry_still_runs(money, tmp_path, monkeypatch):
    app, worker, network = money
    bad = prepared(money)
    # Require a different clan's valid manifest, leaving this one unapproved.
    network.paid = False
    good = prepared(money)
    trust(money, good, tmp_path)
    queue(bad)
    worker.tick()
    with app.state.security.db() as db:
        row = db.scalar(select(Payout).where(Payout.payment_hash == bad[9]))
        pid, last_checked = row.id, db.get(PayoutPoll, row.id).last_checked_at
        db.get(PaymentIntent, row.intent_id).expires_at = "2000-01-01T00:00:00+00:00"
    restarted = TreasuryWorker(worker.settings, provider=worker.provider)
    try:

        def must_not_retry(_):
            raise AssertionError("Persistent backoff was ignored")

        monkeypatch.setattr(restarted, "payout", must_not_retry)
        restarted.tick()
        with app.state.security.db() as db:
            assert db.get(PayoutPoll, pid).last_checked_at == last_checked
            assert db.get(Payout, pid).status == "failed"
            assert db.get(Balance, bad[6]).reserved_msat == 0
    finally:
        restarted.security.engine.dispose()


def test_transient_payment_lookup_does_not_stall_another_clan(money, monkeypatch):
    app, worker, network = money
    bad = prepared(money)
    network.paid = False
    good = prepared(money)
    queue(bad)
    queue(good)
    original = worker.provider.payment

    def payment(payment_hash):
        if payment_hash == bad[9]:
            raise ProviderUnavailable("Synthetic timeout")
        return original(payment_hash)

    monkeypatch.setattr(worker.provider, "payment", payment)
    worker.tick()
    assert network.pay_calls == 1
    with app.state.security.db() as db:
        row = db.scalar(select(Payout).where(Payout.payment_hash == bad[9]))
        assert row.attempts == 0 and row.last_error == "payment_provider_retry"
        assert db.get(Balance, bad[6]).reserved_msat == 101000
        assert db.get(WorkerStatus, "treasury").status == "ready"


def test_global_node_identity_failure_still_stops_all_payments(money, monkeypatch):
    app, worker, network = money
    data = prepared(money)
    queue(data)

    def wrong_node():
        raise ProviderError("Dedicated treasury node identity mismatch")

    monkeypatch.setattr(worker.provider, "verify_node", wrong_node)
    worker.tick()
    assert network.pay_calls == 0
    with app.state.security.db() as db:
        assert db.get(WorkerStatus, "treasury").status == "unavailable"
        assert db.get(Balance, data[6]).reserved_msat == 101000


def test_four_uncertain_payments_do_not_starve_a_new_payment(money, monkeypatch):
    separate_member_addresses(monkeypatch)
    app, worker, network = money
    pending = []
    for _ in range(4):
        network.paid = False
        pending.append(prepared(money))
    for data in pending:
        queue(data)
    network.pending_send = True
    worker.tick()
    assert network.pay_calls == 4
    network.paid = False
    new = prepared(money)
    queue(new)
    worker.tick()
    assert network.pay_calls == 5
    worker.tick()
    assert network.pay_calls == 5  # Reconciliation never repeats the send.
    with app.state.security.db() as db:
        for data in [*pending, new]:
            row = db.scalar(select(Payout).where(Payout.payment_hash == data[9]))
            assert row.attempts == 1 and row.status == "uncertain"
            assert db.get(Balance, data[6]).reserved_msat == 101000


def test_global_trust_configuration_failure_is_not_a_local_deferral(money, tmp_path):
    app, worker, network = money
    data = prepared(money)
    queue(data)
    worker.settings = worker.settings.model_copy(
        update={
            "signer_trust_required": True,
            "signer_trust_public_key": "invalid-key",
            "signer_trust_directory": tmp_path,
        }
    )
    worker.tick()
    assert network.pay_calls == 0
    with app.state.security.db() as db:
        assert db.get(WorkerStatus, "treasury").status == "unavailable"
        row = db.scalar(select(Payout).where(Payout.payment_hash == data[9]))
        assert db.get(PayoutPoll, row.id) is None
        assert db.get(Balance, data[6]).reserved_msat == 101000
