"""KES caps, quote freshness and authenticated historical valuations."""

import time
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from test_live_app import live as live
from test_money import approve, prepared
from test_money import money as money

from clans.fiat_limits import KesQuote, fetch_kes_quote, kes_minor
from clans.money_models import Balance, DispatchAuthorization, Payout
from clans.treasury_provider import ProviderError


def quote():
    return KesQuote(Decimal("10000000"), int(time.time()))


def kes_worker(worker, monkeypatch, **changes):
    worker.settings = worker.settings.model_copy(
        update={
            "payout_budget_currency": "KES",
            "payout_global_24h_kes": 200_000,
            "payout_clan_24h_kes": 50_000,
            "max_payout_kes": 20_000,
            **changes,
        }
    )
    monkeypatch.setattr(worker.provider, "kes_rate", quote)


def queue(money):
    data = prepared(money)
    approve(data[2], data[3], data[8])
    approve(data[4], data[5], data[8])
    return data


def test_round_up_kes_cents_instead_of_floats():
    assert kes_minor(1, "10000000") == 1
    assert kes_minor(100001, "10000000") == 1001
    assert kes_minor(200_000_000, "10000000") == 2_000_000


@pytest.mark.parametrize("age", [301, -31])
def test_stale_and_future_quote_refused(age):
    with pytest.raises(ProviderError):
        KesQuote(Decimal("10000000"), int(time.time()) - age).validate()


@pytest.mark.parametrize("rate", ["NaN", "Infinity", "-1", "0", "9999", "1000000001", None])
def test_bad_rates_fail_closed(rate):
    with pytest.raises(ProviderError):
        kes_minor(100000, rate)


def test_public_quote_client_never_sends_payment_credentials():
    def handle(request):
        assert request.url.host == "api.coingecko.com"
        assert "authorization" not in request.headers
        assert request.url.params["include_last_updated_at"] == "true"
        return httpx.Response(
            200,
            json={
                "bitcoin": {
                    "kes": 10000000,
                    "last_updated_at": int(time.time()),
                }
            },
        )

    assert fetch_kes_quote(transport=httpx.MockTransport(handle)).rate == Decimal(10000000)


def test_kes_payment_and_fee_are_authenticated(money, monkeypatch):
    app, worker, network = money
    queue(money)
    kes_worker(worker, monkeypatch)
    worker.tick()
    assert network.pay_calls == 1
    with app.state.security.db() as db:
        record = db.scalar(select(DispatchAuthorization))
        assert record.kes_per_btc == "10000000"
        assert record.kes_cost_minor == 1010  # 100 sats + 1 sat fee = KES 10.10.
        assert record.kes_rate_published_at is not None


@pytest.mark.parametrize("field", ["kes_per_btc", "kes_cost_minor", "kes_rate_published_at"])
def test_database_rejects_partial_fiat_valuation(money, monkeypatch, field):
    app, worker, _ = money
    queue(money)
    kes_worker(worker, monkeypatch)
    worker.tick()
    with pytest.raises(IntegrityError), app.state.security.db() as db:
        record = db.scalar(select(DispatchAuthorization))
        setattr(record, field, None)
        db.flush()


def test_payout_kes_cap_includes_maximum_fee(money, monkeypatch):
    app, worker, network = money
    data = queue(money)
    kes_worker(worker, monkeypatch, max_payout_kes=10)
    worker.tick()
    assert network.pay_calls == 0
    with app.state.security.db() as db:
        assert db.scalar(select(DispatchAuthorization)) is None
        assert db.get(Balance, data[6]).reserved_msat == 101000


def test_stale_rate_cannot_dispatch_but_completed_payment_still_reconciles(money, monkeypatch):
    app, worker, network = money
    queue(money)
    kes_worker(worker, monkeypatch)
    network.pending_send = True
    worker.tick()
    assert network.pay_calls == 1
    monkeypatch.setattr(worker.provider, "kes_rate", lambda: (_ for _ in ()).throw(ProviderError()))
    with app.state.security.db() as db:
        payment_hash = db.scalar(select(Payout)).payment_hash
    network.outgoing[payment_hash]["status"] = "Complete"
    worker.tick()
    assert network.pay_calls == 1
    with app.state.security.db() as db:
        assert db.scalar(select(Payout)).status == "settled"


def test_fiat_fields_cannot_be_changed_to_revalue_a_dispatched_payment(money, monkeypatch):
    app, worker, network = money
    data = queue(money)
    kes_worker(worker, monkeypatch)
    network.pending_send = True
    worker.tick()
    with app.state.security.db() as db:
        db.scalar(select(DispatchAuthorization)).kes_cost_minor = 1
    network.outgoing[data[9]]["status"] = "Complete"
    worker.tick()
    with app.state.security.db() as db:
        assert db.get(Balance, data[6]).reserved_msat == 101000
        assert db.scalar(select(Payout)).status == "uncertain"
