"""Grant debts counted in KES and repaid in sats, at the rate when each payment was seen."""

import secrets
import time
from decimal import Decimal
from types import SimpleNamespace

from clan_wallet_helpers import DESTINATION
from sqlalchemy import select
from test_clan_wallet_payments import (
    accepted_grant,
    address,
    balance_msat,
    clan,
    drafts,
    fund_clan,
    keys,
    oversight_sign,
    sign,
    tick,
)
from test_reports import laptop_client, period

from clans import activity_catalog, kes_debts
from clans.display_rates import DisplayRate
from clans.live_models import Grant
from clans.models import AuditEvent
from clans.money_models import Debt, LedgerEntry
from clans.treasury_provider import ProviderError
from clans.wallet_models import WalletReceipt

__all__ = ["clan", "keys"]  # pytest fixtures

PRINCIPAL_MINOR = 400_000  # KES 4,000
GRANT_SATS = 40_000  # KES 4,000 at KES 10,000,000 per bitcoin


class Rates:
    """The KES rate both the web app and the chain watcher see. None: no fresh rate."""

    def __init__(self, clan, monkeypatch, per_btc="10000000"):
        self.per_btc = Decimal(per_btc) if per_btc else None
        self.calls = 0
        for rates in (clan["app"].state.security.display_rates, clan["watcher"].rates):
            monkeypatch.setattr(rates, "get", self.get)

    def get(self, currency):
        self.calls += 1
        if self.per_btc is None:
            raise ProviderError("A fresh currency rate is unavailable")
        return DisplayRate(currency, self.per_btc, int(time.time()))

    def set(self, per_btc):
        self.per_btc = Decimal(per_btc) if per_btc else None


def kes_grant(clan, amount="4000"):
    owner, second, third = clan["signers"]
    cid = clan["cid"]
    quote = owner.post(f"/api/clans/{cid}/grant-quote", json={"currency": "KES", "amount": amount})
    assert quote.status_code == 200, quote.text
    response = owner.post(
        f"/api/clans/{cid}/grants",
        json={"purpose": "Stock for the shop", "quote": quote.json()["quote"]},
        headers={"Idempotency-Key": secrets.token_hex(16)},
    )
    assert response.status_code == 200, response.text
    gid = response.json()["grant_id"]
    route = f"/api/clans/{cid}/grants/{gid}"
    for voter in (second, third):
        assert voter.post(route + "/vote", json={"choice": "approve"}).status_code == 200
    assert owner.post(route + "/accept", json={}).status_code == 200
    return gid


def pay_out(clan, gid):
    """Sign, send and confirm the grant payment, so the debt starts."""
    owner, second, third = clan["signers"]
    response = owner.post(
        f"/api/clans/{clan['cid']}/grants/{gid}/payout-address", json={"address": DESTINATION}
    )
    assert response.status_code == 200, response.text
    tick(clan)
    (payout,) = drafts(owner, clan["cid"], grant_id=gid)
    view = sign(clan, third, sign(clan, second, payout).json()).json()
    assert oversight_sign(clan, view).status_code == 200
    tick(clan)
    clan["chain"].mine(payout["txid"])
    tick(clan)


def paid_kes_grant(clan):
    fund_clan(clan, 100_000)
    gid = kes_grant(clan)
    pay_out(clan, gid)
    return gid


def grant_view(clan, gid):
    grants = clan["signers"][0].get(f"/api/clans/{clan['cid']}").json()["grants"]
    return next(g for g in grants if g["id"] == gid)


def repay(clan, gid, sats, *, confirm=True):
    where = address(clan["signers"][0], clan["cid"], "repayment", gid)["address"]
    txid = clan["chain"].pay(where, sats)
    tick(clan)  # seen, not yet confirmed
    if confirm:
        clan["chain"].mine(txid)
        tick(clan)
    return txid


def stored(clan, gid):
    with clan["app"].state.security.db() as db:
        grant, debt = db.get(Grant, gid), db.get(Debt, gid)
        db.expunge_all()
        return grant, debt


def entries(clan, event):
    with clan["app"].state.security.db() as db:
        return [e.amount_msat for e in db.scalars(select(LedgerEntry)) if e.event == event]


def receivable(clan):
    """What the ledger says is still owed on grants, in msat."""
    with clan["app"].state.security.db() as db:
        rows = db.scalars(select(LedgerEntry)).all()
    return sum(e.amount_msat for e in rows if e.debit_account == "grant_receivable") - sum(
        e.amount_msat for e in rows if e.credit_account == "grant_receivable"
    )


def last_settled(clan):
    with clan["app"].state.security.db() as db:
        return db.scalars(
            select(AuditEvent.payload)
            .where(AuditEvent.event_type == "treasury_settled")
            .order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
        ).first()


def test_a_grant_asked_for_in_kes_is_a_kes_debt(clan, monkeypatch):
    rates = Rates(clan, monkeypatch)
    fund_clan(clan, 100_000)
    gid = kes_grant(clan)
    grant, debt = stored(clan, gid)
    assert (grant.obligation_currency, grant.principal_minor) == ("KES", PRINCIPAL_MINOR)
    assert grant.amount_sats == GRANT_SATS  # the sats paid out are fixed at the quote
    assert grant.outstanding_minor == 0 and debt is None  # nothing is owed before payment
    pay_out(clan, gid)
    grant, debt = stored(clan, gid)
    assert grant.status == "in_recovery" and grant.outstanding_minor == PRINCIPAL_MINOR
    assert debt.principal_msat == debt.outstanding_msat == GRANT_SATS * 1000
    view = grant_view(clan, gid)
    assert view["obligation_currency"] == "KES"
    assert view["principal_minor"] == view["outstanding_minor"] == PRINCIPAL_MINOR
    assert view["outstanding_sats_estimate"] == GRANT_SATS
    rates.set("8000000")  # bitcoin fell: the same KES is more sats today
    assert grant_view(clan, gid)["outstanding_sats_estimate"] == 50_000
    rates.set(None)
    assert grant_view(clan, gid)["outstanding_sats_estimate"] is None
    with clan["app"].state.security.db() as db:
        paid = db.scalars(
            select(AuditEvent.payload).where(AuditEvent.event_type == "grant_disbursed")
        ).one()
    assert paid["debt_kes_minor"] == PRINCIPAL_MINOR
    assert "KES 4,000.00" in activity_catalog.summary("grant_disbursed", paid, "")["summary"]


def test_a_partial_repayment_counts_at_the_rate_when_it_was_seen(clan, monkeypatch):
    rates = Rates(clan, monkeypatch)
    gid = paid_kes_grant(clan)
    before = balance_msat(clan)[0]
    rates.set("12500000")  # bitcoin rose: 8,000 sats is KES 1,000
    txid = repay(clan, gid, 8_000, confirm=False)
    rates.set("5000000")  # the rate when it confirms doesn't matter
    clan["chain"].mine(txid)
    tick(clan)
    grant, debt = stored(clan, gid)
    assert grant.outstanding_minor == 300_000 and grant.status == "in_recovery"
    assert grant.recovered_sats == 8_000
    # The debt record keeps the share of the paid-out sats still owed: 3/4 of 40,000.
    assert debt.outstanding_msat == 30_000_000 and debt.recovered_msat == 10_000_000
    assert balance_msat(clan)[0] == before + 8_000_000
    assert entries(clan, "grant_repayment") == [8_000_000]
    # The KES repaid is worth 2,000 more sats of the original grant than were paid.
    assert entries(clan, "exchange_loss") == [2_000_000]
    assert receivable(clan) == debt.outstanding_msat
    with clan["app"].state.security.db() as db:
        receipt = db.scalars(select(WalletReceipt).where(WalletReceipt.txid == txid)).one()
        assert receipt.status == "confirmed" and receipt.kes_per_btc == "12500000"
        assert receipt.kes_credited_minor == 100_000 and receipt.kes_owed_after_minor == 300_000
        assert receipt.credit_note is None
    payload = last_settled(clan)
    assert payload["credited_kes_minor"] == 100_000 and payload["kes_per_btc"] == "12500000"
    explained = activity_catalog.summary("treasury_settled", payload, "Organizer")["summary"]
    assert "KES 1,000.00" in explained and "KES 12,500,000 per bitcoin" in explained
    assert "KES 3,000.00 is still owed" in explained
    facts = {f["label"]: f["value"] for f in activity_catalog.details("treasury_settled", payload)}
    assert facts["Counted towards the grant"] == "KES 1,000.00"
    assert facts["Rate used"] == "KES 12,500,000 per bitcoin"
    (row,) = clan["signers"][0].get(f"/api/clans/{clan['cid']}/wallet/receipts").json()
    assert row["kes_credited_minor"] == 100_000 and row["kes_owed_after_minor"] == 300_000
    view = grant_view(clan, gid)
    assert view["outstanding_minor"] == 300_000
    assert view["outstanding_sats_estimate"] == 60_000  # KES 3,000 at KES 5,000,000


def test_a_repayment_waits_for_a_rate_and_is_never_guessed(clan, monkeypatch):
    rates = Rates(clan, monkeypatch)
    gid = paid_kes_grant(clan)
    before = balance_msat(clan)[0]
    rates.set(None)
    txid = repay(clan, gid, 10_000)
    tick(clan)
    with clan["app"].state.security.db() as db:
        receipt = db.scalars(select(WalletReceipt).where(WalletReceipt.txid == txid)).one()
        assert receipt.status == "pending" and receipt.confirmations >= 3
        assert receipt.credit_note == kes_debts.WAITING_FOR_RATE
        assert receipt.kes_per_btc is None and receipt.credited_at is None
    assert stored(clan, gid)[0].outstanding_minor == PRINCIPAL_MINOR
    assert balance_msat(clan)[0] == before
    (row,) = clan["signers"][0].get(f"/api/clans/{clan['cid']}/wallet/receipts").json()
    assert row["status"] == "pending" and row["credit_note"] == "waiting_for_rate"
    # A fresh rate arrives: the payment is counted at it, once.
    rates.set("10000000")
    tick(clan)
    tick(clan)
    grant, _ = stored(clan, gid)
    assert grant.outstanding_minor == 300_000
    assert balance_msat(clan)[0] == before + 10_000_000
    assert entries(clan, "grant_repayment") == [10_000_000]
    with clan["app"].state.security.db() as db:
        receipt = db.get(WalletReceipt, receipt.id)
        assert receipt.status == "confirmed" and receipt.credit_note is None
        assert receipt.kes_per_btc == "10000000" and receipt.kes_rate_seen_at


def test_kes_paid_beyond_the_debt_is_clan_money(clan, monkeypatch):
    Rates(clan, monkeypatch)
    gid = paid_kes_grant(clan)
    repay(clan, gid, 50_000)  # KES 5,000 for a KES 4,000 debt
    grant, debt = stored(clan, gid)
    assert grant.status == "recovered" and grant.outstanding_minor == 0
    assert grant.recovered_sats == GRANT_SATS
    assert debt.outstanding_msat == 0 and debt.recovered_msat == debt.principal_msat
    assert entries(clan, "grant_repayment") == [40_000_000]
    assert entries(clan, "recovery_surplus") == [10_000_000]
    assert entries(clan, "exchange_gain") == entries(clan, "exchange_loss") == []
    assert receivable(clan) == 0
    payload = last_settled(clan)
    assert payload["surplus_kes_minor"] == 100_000 and payload["owed_after_kes_minor"] == 0
    explained = activity_catalog.summary("treasury_settled", payload, "")["summary"]
    assert "extra KES 1,000.00 is kept as clan money" in explained
    assert "fully repaid" in explained


def test_less_than_one_kes_left_counts_as_repaid(clan, monkeypatch):
    Rates(clan, monkeypatch)
    gid = paid_kes_grant(clan)
    repay(clan, gid, 39_995)  # KES 3,999.50 of KES 4,000
    grant, debt = stored(clan, gid)
    assert grant.status == "recovered" and grant.outstanding_minor == 0
    assert debt.outstanding_msat == 0
    assert last_settled(clan)["rounded_off_kes_minor"] == 50
    assert entries(clan, "grant_repayment") == [39_995_000]
    assert entries(clan, "exchange_loss") == [5_000]
    assert receivable(clan) == 0


def test_reports_count_kes_debts_in_kes(clan, monkeypatch, tmp_path):
    rates = Rates(clan, monkeypatch)
    gid = paid_kes_grant(clan)
    rates.set("12500000")
    repay(clan, gid, 8_000)  # KES 1,000
    laptop = laptop_client(clan, tmp_path)
    start, end = period()
    data = laptop.get(f"/api/oversight/report?from={start}&to={end}").json()
    (row,) = data["clans"]
    assert (row["paid_kes"], row["repaid_kes"], row["outstanding_kes"]) == (4000, 1000, 3000)
    assert (row["paid_sats"], row["repaid_sats"], row["outstanding_sats"]) == (
        40_000,
        8_000,
        30_000,
    )
    assert row["repayment_rate"] == 0.25  # in KES, not 8,000 of 40,000 sats
    assert data["totals"]["outstanding_kes"] == 3000
    sheet = laptop.get(f"/api/oversight/report?from={start}&to={end}&format=csv").text
    assert "paid_kes" in sheet.splitlines()[0] and "outstanding_kes" in sheet.splitlines()[0]


def test_sats_grants_stay_counted_in_sats(clan, monkeypatch):
    rates = Rates(clan, monkeypatch)
    fund_clan(clan, 100_000)
    gid = accepted_grant(clan)
    pay_out(clan, gid)
    grant, _ = stored(clan, gid)
    assert grant.obligation_currency == "BTC" and grant.principal_minor == GRANT_SATS
    calls = rates.calls
    repay(clan, gid, 15_000)
    assert rates.calls == calls  # a sats debt never needs a rate
    grant, debt = stored(clan, gid)
    assert grant.outstanding_minor == 25_000 and debt.outstanding_msat == 25_000_000
    view = grant_view(clan, gid)
    assert view["obligation_currency"] == "BTC"
    assert view["outstanding_minor"] == view["outstanding_sats_estimate"] == 25_000
    assert "credited_kes_minor" not in last_settled(clan)
    (row,) = clan["signers"][0].get(f"/api/clans/{clan['cid']}/wallet/receipts").json()
    assert row["kes_credited_minor"] is None and row["credit_note"] is None


def test_a_grant_asked_for_in_another_currency_stays_in_sats(clan, monkeypatch):
    Rates(clan, monkeypatch)
    owner = clan["signers"][0]
    cid = clan["cid"]
    quote = owner.post(f"/api/clans/{cid}/grant-quote", json={"currency": "USD", "amount": "30"})
    response = owner.post(
        f"/api/clans/{cid}/grants",
        json={"purpose": "Stock for the shop", "quote": quote.json()["quote"]},
        headers={"Idempotency-Key": secrets.token_hex(16)},
    )
    grant, _ = stored(clan, response.json()["grant_id"])
    assert grant.obligation_currency == "BTC" and grant.principal_minor == grant.amount_sats


class Book:
    def __init__(self):
        self.rows = []

    def add(self, row):
        self.rows.append((row.event, row.amount_msat, row.debit_account, row.credit_account))


def kes_debt(owed=PRINCIPAL_MINOR, outstanding_msat=GRANT_SATS * 1000):
    grant = SimpleNamespace(
        obligation_currency="KES",
        principal_minor=PRINCIPAL_MINOR,
        outstanding_minor=owed,
        recovered_sats=0,
        status="in_recovery",
    )
    debt = SimpleNamespace(
        principal_msat=GRANT_SATS * 1000,
        outstanding_msat=outstanding_msat,
        recovered_msat=GRANT_SATS * 1000 - outstanding_msat,
    )
    return grant, debt


def test_when_bitcoin_falls_the_extra_sats_are_an_exchange_gain():
    grant, debt = kes_debt()
    book = Book()
    rate = kes_debts.Rate(Decimal("5000000"), 1)  # KES 1,000 is now 20,000 sats
    counted, facts = kes_debts.repay(book, "c", grant, debt, 20_000_000, "ref", rate)
    assert counted == 20_000_000 and facts["credited_kes_minor"] == 100_000
    assert grant.outstanding_minor == 300_000 and debt.outstanding_msat == 30_000_000
    assert book.rows == [
        ("grant_repayment", 10_000_000, "bitcoin_custody", "grant_receivable"),
        ("exchange_gain", 10_000_000, "bitcoin_custody", "clan_capital"),
    ]
    assert debt.principal_msat == debt.outstanding_msat + debt.recovered_msat


def test_a_payment_after_full_repayment_is_all_clan_money():
    grant, debt = kes_debt(owed=0, outstanding_msat=0)
    book = Book()
    counted, facts = kes_debts.repay(book, "c", grant, debt, 5_000_000, "ref", None)
    assert counted == 0 and book.rows == [] and facts == {"owed_after_kes_minor": 0}
