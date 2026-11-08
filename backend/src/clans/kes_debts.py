"""Grant debts counted in KES and repaid in sats.

A grant asked for in KES is a KES debt. The sats paid out stay fixed at the quote, but the
member owes the KES amount they asked for: `Grant.principal_minor` and
`Grant.outstanding_minor` hold KES cents, and `obligation_currency` is "KES". Older grants,
and grants asked for in sats, stay "BTC" debts, where those fields hold sats.

How a repayment in sats counts towards a KES debt:

- It's valued at the KES/BTC rate the chain watcher had when it first saw the payment
  (the rate when the member paid). The rate, and the KES counted, are kept with the receipt.
- Without a fresh rate nothing is guessed: the payment waits, uncredited, and is tried again.
- KES beyond what's owed is clan money (`recovery_surplus`). Only the sats worth that extra
  KES are surplus; the rest pay the debt.
- When less than KES 1 is left after a repayment, the grant counts as repaid.

`Debt` (msat) stays the record of the sats paid out. For a KES debt, its `outstanding_msat`
is the share of those sats still owed, in proportion to the KES still owed, so that
`principal_msat = outstanding_msat + recovered_msat` holds and `outstanding_msat > 0`
exactly while KES is owed. The sats a member actually pays can be more or fewer than that
share, because the Bitcoin price moves. The difference is booked to the clan as an exchange
gain or loss, so every sat received is in the ledger and the grant receivable clears to zero.
"""

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from clans.money_service import ledger

KES = "KES"
# A repayment that leaves less than this owed (KES 1, in cents) repays the grant.
ROUND_OFF_MINOR = 100
WAITING_FOR_RATE = "waiting_for_rate"


@dataclass(frozen=True)
class Rate:
    """KES per bitcoin, and when the rate source published it (Unix seconds)."""

    per_btc: Decimal
    published_at: int

    @property
    def text(self) -> str:
        return format(self.per_btc, "f")


def is_kes(grant) -> bool:
    return grant.obligation_currency == KES


def kes_minor(msat: int, rate: Rate) -> int:
    """KES cents for an amount, to the nearest cent."""
    return int(
        (Decimal(msat) * rate.per_btc / Decimal(10**9)).to_integral_value(rounding=ROUND_HALF_UP)
    )


def msat_for(minor: int, rate: Rate) -> int:
    """The msat that are worth `minor` KES cents, rounded up to a whole sat."""
    sats = (Decimal(minor) * Decimal(1_000_000) / rate.per_btc).to_integral_value(
        rounding=ROUND_CEILING
    )
    return int(sats) * 1000


def sats_estimate(minor: int, per_btc: Decimal) -> int:
    """About how many sats `minor` KES cents is today, rounded up. For display only."""
    return msat_for(minor, Rate(per_btc, 0)) // 1000


def needs_rate(grant, debt) -> bool:
    return bool(debt) and is_kes(grant) and grant.outstanding_minor > 0


def repay(db, clan_id: str, grant, debt, amount_msat: int, reference: str, rate: Rate | None):
    """Count a repayment towards a grant's debt. Returns the msat counted and the facts.

    The caller books the rest (`amount_msat - counted`) as clan money, and adds the money
    to the clan balance. For a KES debt with KES still owed, `rate` must be given.
    """
    if not is_kes(grant):
        counted = min(amount_msat, debt.outstanding_msat)
        debt.outstanding_msat -= counted
        debt.recovered_msat += counted
        grant.outstanding_minor = (debt.outstanding_msat + 999) // 1000
        grant.recovered_sats = debt.recovered_msat // 1000
        if debt.outstanding_msat == 0:
            grant.status = "recovered"
        ledger(
            db,
            clan_id,
            "grant_repayment",
            reference + ":recovery",
            counted,
            "bitcoin_custody",
            "grant_receivable",
        )
        return counted, {}

    owed = grant.outstanding_minor
    if owed == 0:
        # Already repaid: all of it is clan money.
        facts = {"owed_after_kes_minor": 0}
        if rate:
            facts |= {"kes_per_btc": rate.text, "surplus_kes_minor": kes_minor(amount_msat, rate)}
        return 0, facts
    if rate is None:
        raise ValueError("A KES debt needs the rate the repayment was seen at")
    value = kes_minor(amount_msat, rate)
    credited = min(value, owed)
    left = owed - credited
    rounded_off = left if left < ROUND_OFF_MINOR else 0
    left -= rounded_off
    # Overpaid: only the sats worth the extra KES are surplus.
    counted = min(amount_msat, msat_for(owed, rate)) if value > owed else amount_msat
    before = debt.outstanding_msat
    after = 0 if left == 0 else -(-debt.principal_msat * left // grant.principal_minor)
    after = min(after, before)
    cleared = before - after
    debt.outstanding_msat, debt.recovered_msat = after, debt.principal_msat - after
    grant.outstanding_minor = left
    grant.recovered_sats += counted // 1000
    if left == 0:
        grant.status = "recovered"
    ledger(
        db,
        clan_id,
        "grant_repayment",
        reference + ":recovery",
        min(counted, cleared),
        "bitcoin_custody",
        "grant_receivable",
    )
    if counted > cleared:
        # Bitcoin fell since the grant was paid: the same KES bought more sats.
        ledger(
            db,
            clan_id,
            "exchange_gain",
            reference + ":exchange",
            counted - cleared,
            "bitcoin_custody",
            "clan_capital",
        )
    elif cleared > counted:
        # Bitcoin rose: the KES repaid is worth fewer sats than were paid out.
        ledger(
            db,
            clan_id,
            "exchange_loss",
            reference + ":exchange",
            cleared - counted,
            "exchange_losses",
            "grant_receivable",
        )
    facts = {
        "kes_per_btc": rate.text,
        "kes_rate_published_at": rate.published_at,
        "credited_kes_minor": credited,
        "owed_after_kes_minor": left,
    }
    if rounded_off:
        facts["rounded_off_kes_minor"] = rounded_off
    if value > owed:
        facts["surplus_kes_minor"] = value - owed
    return counted, facts
