"""Public display rates and short-lived, account-bound grant quotes.

These estimates do not replace the treasury worker's independent KES payout limits.
"""

import hmac
import json
import re
import threading
import time
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal, InvalidOperation

import httpx
from fastapi import HTTPException

from clans.live_security import b64, unb64
from clans.treasury_provider import ProviderError

CURRENCIES = frozenset(
    {"KES", "USD", "EUR", "GBP", "UGX", "TZS", "ZAR", "NGN", "CAD", "AUD", "INR", "CHF", "AED"}
)
MAX_AGE = 300
QUOTE_LIFETIME = 120


@dataclass(frozen=True)
class DisplayRate:
    currency: str
    per_btc: Decimal
    published_at: int

    def validate(self):
        if (
            self.currency not in CURRENCIES
            or not self.per_btc.is_finite()
            or not Decimal("0.01") <= self.per_btc <= Decimal("1000000000000")
            or not isinstance(self.published_at, int)
            or isinstance(self.published_at, bool)
            or not -30 <= time.time() - self.published_at <= MAX_AGE
        ):
            raise ProviderError("A fresh currency rate is unavailable")
        return self

    def public(self):
        self.validate()
        return {
            "currency": self.currency,
            "per_btc": format(self.per_btc, "f"),
            "published_at": self.published_at,
            "valid_until": self.published_at + MAX_AGE,
            "source": "CoinGecko",
        }


class DisplayRates:
    def __init__(self, *, transport=None):
        self.transport = transport
        self.lock = threading.Lock()
        self.cached = {}
        self.last_attempt = float("-inf")

    def get(self, currency):
        if currency not in CURRENCIES:
            raise ProviderError("This display currency is not supported")
        with self.lock:
            # Fetch all currencies together. Polling users never cause one upstream call each.
            if time.monotonic() - self.last_attempt >= 60:
                self.last_attempt = time.monotonic()
                try:
                    with httpx.Client(
                        trust_env=False,
                        follow_redirects=False,
                        transport=self.transport,
                        timeout=httpx.Timeout(12, connect=4),
                    ) as client:
                        response = client.get(
                            "https://api.coingecko.com/api/v3/simple/price",
                            params={
                                "ids": "bitcoin",
                                "vs_currencies": ",".join(sorted(c.lower() for c in CURRENCIES)),
                                "include_last_updated_at": "true",
                            },
                        )
                        response.raise_for_status()
                        row = response.json()["bitcoin"]
                        rates = {}
                        for code in CURRENCIES:
                            if code.lower() not in row:
                                continue
                            raw = str(row[code.lower()])
                            if len(raw) > 60:
                                raise ValueError("Invalid rate")
                            rates[code] = DisplayRate(
                                code, Decimal(raw), row["last_updated_at"]
                            ).validate()
                        self.cached = rates
                except (
                    httpx.HTTPError,
                    ValueError,
                    KeyError,
                    TypeError,
                    InvalidOperation,
                    ProviderError,
                ):
                    # A previous rate may be used only while its publisher timestamp is fresh.
                    pass
            rate = self.cached.get(currency)
            if not rate:
                raise ProviderError("A fresh currency rate is unavailable")
            return rate.validate()


def amount_minor(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,12}(?:\.[0-9]{1,2})?", value):
        raise HTTPException(422, "Enter an amount with up to two decimal places.")
    minor = int(Decimal(value) * 100)
    if minor <= 0:
        raise HTTPException(422, "Enter an amount above zero.")
    return minor


def make_grant_quote(security, user_id, clan_id, currency, amount):
    try:
        rate = security.display_rates.get(currency)
    except ProviderError as exc:
        raise HTTPException(
            503,
            "The current rate is unavailable. Try again shortly or choose another currency.",
        ) from exc
    minor = amount_minor(amount)
    sats = int(
        (Decimal(minor) * 1_000_000 / rate.per_btc).to_integral_value(rounding=ROUND_CEILING)
    )
    if not 1 <= sats <= 100_000_000:
        raise HTTPException(422, "This amount is outside the allowed grant size.")
    payload = {
        "user": user_id,
        "clan": clan_id,
        "currency": currency,
        "amount_minor": minor,
        "amount_sats": sats,
        "per_btc": format(rate.per_btc, "f"),
        "published_at": rate.published_at,
        "expires_at": min(int(time.time()) + QUOTE_LIFETIME, rate.published_at + MAX_AGE),
    }
    encoded = b64(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    return {
        **payload,
        "source": "CoinGecko",
        "quote": encoded + "." + security.mac("grant-quote:" + encoded),
    }


def read_grant_quote(security, token, user_id, clan_id):
    try:
        encoded, signature = token.split(".")
        if not hmac.compare_digest(signature, security.mac("grant-quote:" + encoded)):
            raise ValueError
        payload = json.loads(unb64(encoded))
        if payload["user"] != user_id or payload["clan"] != clan_id:
            raise ValueError
        if payload["expires_at"] <= time.time():
            raise HTTPException(409, "The rate has changed. Check the amount again before sending.")
        return payload
    except (ValueError, KeyError, TypeError, UnicodeError) as exc:
        raise HTTPException(400, "Check the amount again before sending your request.") from exc
