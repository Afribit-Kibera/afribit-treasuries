"""Local money never becomes an unsigned, stale or cross-account grant amount."""

import json
import secrets
import time
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select
from test_live_app import clan, join, signup
from test_live_app import live as live

from clans.display_rates import DisplayRate, DisplayRates, amount_minor
from clans.live_models import Grant
from clans.live_security import b64, unb64
from clans.treasury_provider import ProviderError


def test_public_rate_cache_freshness_and_no_credentials(monkeypatch):
    calls = []
    published = int(time.time())

    def handle(request):
        calls.append(request)
        assert "authorization" not in request.headers
        assert request.url.host == "api.coingecko.com"
        assert request.url.params["include_last_updated_at"] == "true"
        return httpx.Response(
            200, json={"bitcoin": {"kes": 10_000_000, "usd": 80_000, "last_updated_at": published}}
        )

    rates = DisplayRates(transport=httpx.MockTransport(handle))
    assert rates.get("KES").public()["per_btc"] == "10000000"
    assert rates.get("USD").currency == "USD"
    assert len(calls) == 1
    with pytest.raises(ProviderError):
        rates.get("TZS")  # A missing pair must not silently become USD.
    monkeypatch.setattr("clans.display_rates.time.time", lambda: published + 301)
    with pytest.raises(ProviderError):
        rates.get("KES")


@pytest.mark.parametrize(
    "value", ["0", "-1", "1.001", "NaN", "Infinity", "1e3", "1,000", "9999999999999", 1, True]
)
def test_amounts_require_exact_positive_decimal_text(value):
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        amount_minor(value)


@pytest.mark.parametrize(
    "rate,age", [("NaN", 0), ("0", 0), ("1e40", 0), ("10000000", 301), ("10000000", -31)]
)
def test_invalid_display_rate_is_rejected(rate, age):
    with pytest.raises(ProviderError):
        DisplayRate("KES", Decimal(rate), int(time.time()) - age).validate()


def test_grant_quote_binding_rounding_expiry_and_idempotency(live, monkeypatch):
    organizer, *_ = signup(live, "Organizer")
    cid = clan(organizer)
    for name in ["Signer Two", "Signer Three"]:
        member, *_ = signup(live, name)
        join(organizer, member, cid)
    borrower, *_ = signup(live, "Borrower")
    join(organizer, borrower, cid, signer=False)
    published = int(time.time())
    rate = DisplayRate("KES", Decimal("10000001"), published)
    monkeypatch.setattr(live.state.security.display_rates, "get", lambda currency: rate)
    result = borrower.post(
        f"/api/clans/{cid}/grant-quote", json={"currency": "KES", "amount": "1.01"}
    )
    assert result.status_code == 200, result.text
    quote = result.json()
    assert quote["amount_sats"] == 11  # Round up once to a whole sat; never float.
    assert quote["amount_minor"] == 101
    body = {"purpose": "Buy stock for my stall", "quote": quote["quote"]}
    endpoint = f"/api/clans/{cid}/grants"
    headers = {"Idempotency-Key": secrets.token_hex(16)}
    # The same signed amount cannot be used by another clan member.
    assert organizer.post(endpoint, json=body, headers=headers).status_code == 400
    encoded, signature = quote["quote"].split(".")
    forged = json.loads(unb64(encoded))
    forged["amount_sats"] = 1000
    bad_token = b64(json.dumps(forged).encode()) + "." + signature
    assert (
        borrower.post(endpoint, json={**body, "quote": bad_token}, headers=headers).status_code
        == 400
    )
    # A client cannot override a signed quote with its own integer.
    assert (
        borrower.post(endpoint, json={**body, "amount_sats": 999}, headers=headers).status_code
        == 422
    )
    submitted = borrower.post(endpoint, json=body, headers=headers)
    assert submitted.status_code == 200, submitted.text
    with live.state.security.db() as db:
        grant = db.get(Grant, submitted.json()["grant_id"])
        assert grant.amount_sats == 11
        assert grant.policy_snapshot["request_value"]["amount_minor"] == 101
        assert db.scalar(select(Grant.id).where(Grant.id == grant.id))
    monkeypatch.setattr("clans.display_rates.time.time", lambda: published + 121)
    # A lost response may safely be retried even after the quote expires.
    assert borrower.post(endpoint, json=body, headers=headers).json() == submitted.json()
    assert (
        borrower.post(
            endpoint, json=body, headers={"Idempotency-Key": secrets.token_hex(16)}
        ).status_code
        == 409
    )


def test_rate_endpoints_require_session_and_quote_requires_membership(live, monkeypatch):
    from test_live_app import client

    assert client(live).get("/api/rates/KES").status_code == 401
    organizer, *_ = signup(live)
    cid = clan(organizer)
    outsider, *_ = signup(live, "Outside Member")
    assert (
        outsider.post(
            f"/api/clans/{cid}/grant-quote", json={"currency": "KES", "amount": "100"}
        ).status_code
        == 403
    )
    monkeypatch.setattr(
        live.state.security.display_rates,
        "get",
        lambda _: (_ for _ in ()).throw(ProviderError("No rate")),
    )
    assert organizer.get("/api/rates/KES").status_code == 503
    assert (
        organizer.post(
            f"/api/clans/{cid}/grant-quote", json={"currency": "KES", "amount": "100"}
        ).status_code
        == 503
    )


def test_members_on_one_connection_have_independent_display_rate_quotas(live, monkeypatch):
    first, *_ = signup(live, "First Member")
    second, *_ = signup(live, "Second Member")
    security = live.state.security
    original_limit = security.limit

    def short_quota(request, scope, maximum, seconds):
        return original_limit(request, scope, 1, seconds)

    monkeypatch.setattr(security, "limit", short_quota)
    monkeypatch.setattr(
        security.display_rates,
        "get",
        lambda _: DisplayRate("KES", Decimal("10000000"), int(time.time())),
    )
    assert first.get("/api/rates/KES").status_code == 200
    assert first.get("/api/rates/KES").status_code == 429
    assert second.get("/api/rates/KES").status_code == 200
