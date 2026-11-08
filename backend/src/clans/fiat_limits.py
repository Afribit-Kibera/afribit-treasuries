"""Integer KES-cent valuation of exact millisatoshi exposure. No float arithmetic."""

import time
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal, InvalidOperation

import httpx

from clans.treasury_provider import ProviderError


@dataclass(frozen=True)
class KesQuote:
    rate: Decimal
    published_at: int

    def validate(self):
        rate_value(self.rate)
        if (
            not isinstance(self.published_at, int)
            or isinstance(self.published_at, bool)
            or not -30 <= time.time() - self.published_at <= 300
        ):
            raise ProviderError("The BTC/KES quote is stale or invalid")
        return self


def fetch_kes_quote(*, transport=None):
    """Independent public client: never forwards a BTCPay Authorization header."""
    try:
        with httpx.Client(
            trust_env=False,
            follow_redirects=False,
            transport=transport,
            timeout=httpx.Timeout(15, connect=5),
        ) as client:
            response = client.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={
                    "ids": "bitcoin",
                    "vs_currencies": "kes",
                    "include_last_updated_at": "true",
                },
            )
            response.raise_for_status()
            row = response.json()["bitcoin"]
            return KesQuote(rate_value(row["kes"]), row["last_updated_at"]).validate()
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise ProviderError("A fresh BTC/KES quote is unavailable") from exc


def rate_value(value):
    try:
        rate = Decimal(str(value))
        if not rate.is_finite() or not Decimal(10_000) <= rate <= Decimal(1_000_000_000):
            raise ValueError
        if len(str(value)) > 60:
            raise ValueError
        return rate
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ProviderError("A valid current BTC/KES rate is required") from exc


def kes_minor(msat, rate):
    if not isinstance(msat, int) or isinstance(msat, bool) or msat <= 0:
        raise ProviderError("A positive millisatoshi exposure is required")
    return int(
        (Decimal(msat) * rate_value(rate) / Decimal(1_000_000_000)).to_integral_value(
            rounding=ROUND_CEILING
        )
    )
