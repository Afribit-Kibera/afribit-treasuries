"""Chain watcher for clan wallets: the only process that credits money, builds payouts and
broadcasts them. It holds no key that can spend. Run it with `python -m clans.chain_watcher`.

Each cycle, for every active clan wallet, it:

1. reads the wallet from a block explorer;
2. records payments to clan addresses, and credits them once they have 3 confirmations;
3. links outgoing payments to their payouts, and raises an alarm for any it didn't build;
4. books payouts as paid once they have 3 confirmations;
5. builds a payout for each beneficiary address waiting, from confirmed coins only;
6. offers a higher-fee version of a sent payout that's stuck, for the clan to sign again;
7. builds a refresh before any coin's recovery wait nears its end, and, for a retired
   wallet, a move of its coins into the clan's newest wallet;
8. checks fully signed payouts with BDK, which verifies every signature, then broadcasts.

Retired wallets stay watched, so a late payment to an old address is still credited and
moved across.

Nothing is ever reset to hide an uncertain payment: a payout that leaves the network is
broadcast again, and a reorganisation after crediting raises an alarm.
"""

import argparse
import json
import math
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol

import bdkpython as bdk
from sqlalchemy import func, select, text

from clans import kes_debts
from clans.clan_wallet import (
    MAX_CHANGE_INDEX,
    SAT_KWU_PER_SAT_VB,
    ClanWallet,
    ClanWalletError,
    Recipient,
    SignatureError,
    fee_rate_kwu,
)
from clans.display_rates import DisplayRates
from clans.live_config import LiveSettings
from clans.live_models import Grant
from clans.live_security import Security
from clans.models import AuditEvent, Clan, User, now_iso
from clans.money_models import Debt
from clans.money_service import ledger, reconciled
from clans.treasury_provider import ProviderError
from clans.wallet_api import active_wallet
from clans.wallet_models import (
    LIVE_PAYOUT_STATUSES,
    ChainStatus,
    ClanWalletRecord,
    WalletAddress,
    WalletPayout,
    WalletPayoutRequest,
    WalletReceipt,
)
from clans.wallet_payments import (
    REORG_DEPTH,
    actor,
    alarm,
    key_origins,
    psbt_details,
    record_policy,
    signatures,
)

LOCK_ID = 24110501
INTERVAL_SECONDS = 30
# When the block explorer refuses or fails, wait longer each time, up to this.
MAX_BACKOFF_SECONDS = 600


def next_delay(failed_cycles: int) -> int:
    """30 seconds normally; doubling after each failed cycle, up to 10 minutes."""
    return min(INTERVAL_SECONDS * 2 ** min(failed_cycles, 10), MAX_BACKOFF_SECONDS)


# A refresh is built once the oldest coin has waited 5/6 of the recovery wait: about a month
# before the end of a 6-month wait, or 5 days before the end of the shortest (30-day) one.
REFRESH_MARGIN = 6
# Coins per refresh or move, oldest first. More are moved by the next one.
MAX_SWEEP_COINS = 25
# The fee preview needs only the largest coins; this keeps the row small.
MAX_PREVIEW_COINS = 50
BLOCKS_PER_DAY = 144


@dataclass(frozen=True)
class TxState:
    found: bool
    height: int | None = None


class Chain(Protocol):
    def tip_height(self) -> int: ...
    def fee_rate(self) -> float: ...
    def sync(self, wallet: ClanWallet) -> None: ...
    def state(self, txid: str) -> TxState: ...
    def broadcast(self, raw_hex: str) -> None: ...


def rate_columns(rate: float) -> dict:
    """A payout's exact fee rate, and the whole sat/vB that older screens show."""
    return {"fee_rate_sat_vb": math.ceil(rate), "fee_rate_sat_kwu": fee_rate_kwu(rate)}


def payout_rate(payout: WalletPayout) -> float:
    """The fee rate a payout was built with, in sat/vB. Older rows kept whole numbers."""
    if payout.fee_rate_sat_kwu:
        return payout.fee_rate_sat_kwu / SAT_KWU_PER_SAT_VB
    return float(payout.fee_rate_sat_vb)


class EsploraChain:
    """A public or self-hosted Esplora explorer. Read-only apart from broadcasting."""

    def __init__(self, url: str):
        self.client = bdk.EsploraClient(url)

    def tip_height(self) -> int:
        return self.client.get_height()

    def fee_rate(self) -> float:
        """The rate to confirm within about an hour, in sat/vB to a thousandth."""
        try:
            estimates = self.client.get_fee_estimates()
        except bdk.EsploraError.HttpResponse as exc:
            # mempool.space answers with 203 (a cached copy). BDK accepts only 200, but
            # the body is still the estimates. Any other status is a real failure.
            if not 200 <= exc.status < 300:
                raise
            estimates = {int(k): float(v) for k, v in json.loads(exc.error_message).items()}
        rate = estimates.get(6) or min(estimates.values(), default=1)
        # Rounded up to a thousandth, not to a whole sat/vB: at low fees that doubled them.
        return min(1_000.0, max(1.0, math.ceil(round(rate * 1000, 6)) / 1000))

    def sync(self, wallet: ClanWallet) -> None:
        request = wallet.wallet.start_sync_with_revealed_spks().build()
        wallet.wallet.apply_update(self.client.sync(request, 4))

    def state(self, txid: str) -> TxState:
        info = self.client.get_tx_info(bdk.Txid.from_string(txid))
        if info is None:
            return TxState(False)
        return TxState(True, info.status.block_height if info.status.confirmed else None)

    def broadcast(self, raw_hex: str) -> None:
        self.client.broadcast(bdk.Transaction(bytes.fromhex(raw_hex)))


def outpoint(value: str) -> bdk.OutPoint:
    txid, vout = value.split(":")
    return bdk.OutPoint(txid=bdk.Txid.from_string(txid), vout=int(vout))


def outpoint_text(value: bdk.OutPoint) -> str:
    return f"{value.txid}:{value.vout}"


class ChainWatcher:
    def __init__(self, settings, *, chain: Chain | None = None):
        if not settings.clan_wallets_enabled:
            raise RuntimeError("Clan wallets are switched off")
        self.settings = settings
        self.security = Security(settings)
        self.chain = chain or EsploraChain(settings.esplora_url)
        self.wallets: dict[str, ClanWallet] = {}
        # Wallet id -> error type from the last cycle. One clan's problem never stops others.
        self.failures: dict[str, str] = {}
        self.watched = 0
        self.tip = 0
        # The public KES rate, as the app shows it. Read only while a KES debt is open.
        self.rates = DisplayRates()
        self.kes_rate: kes_debts.Rate | None = None

    # One cycle ----------------------------------------------------------------------------

    def tick(self):
        tip, rate = self.chain.tip_height(), self.chain.fee_rate()
        self.tip = tip
        with self.security.db() as db:
            status = db.get(ChainStatus, self.settings.clan_wallet_network)
            if not status:
                status = ChainStatus(network=self.settings.clan_wallet_network)
                db.add(status)
            status.tip_height = tip
            status.fee_rate_sat_vb = math.ceil(rate)
            status.fee_rate_sat_kwu = fee_rate_kwu(rate)
            status.observed_at, status.message = now_iso(), ""
            kes_owed = db.scalar(
                select(Grant.id)
                .where(Grant.obligation_currency == kes_debts.KES, Grant.status == "in_recovery")
                .limit(1)
            )
            ids = db.scalars(
                select(ClanWalletRecord.id).where(
                    ClanWalletRecord.status.in_(["active", "retired"]),
                    ClanWalletRecord.activated_at.is_not(None),
                    ClanWalletRecord.network == self.settings.clan_wallet_network,
                )
            ).all()
        # Read outside any transaction, so a slow rate source holds up no clan.
        self.kes_rate = self.fetch_kes_rate() if kes_owed else None
        self.failures = {}
        self.watched = len(ids)
        for wallet_id in ids:
            try:
                self.watch(wallet_id, tip, rate)
            except Exception as exc:
                self.failures[wallet_id] = type(exc).__name__
                print(f"Clan wallet {wallet_id} skipped this cycle: {type(exc).__name__}")

    def fetch_kes_rate(self) -> kes_debts.Rate | None:
        try:
            found = self.rates.get(kes_debts.KES)
        except ProviderError:
            print("No fresh KES rate this cycle; KES repayments wait for one.")
            return None
        return kes_debts.Rate(found.per_btc, found.published_at)

    def watch(self, wallet_id: str, tip: int, rate: float):
        with self.security.db() as db:
            record = db.get(ClanWalletRecord, wallet_id)
            policy = record_policy(db, record)
            wallet = self.wallet_for(db, record, policy)
        # Network reads happen outside the transaction so clan requests aren't held up.
        self.chain.sync(wallet)
        with self.security.db() as db:
            db.scalar(select(Clan).where(Clan.id == record.clan_id).with_for_update())
            record = db.get(ClanWalletRecord, wallet_id)
            record.balance_sats = wallet.balance_sats()
            record.spendable_coins = self.spendable(db, record, wallet)
            self.receipts(db, record, wallet, tip)
            self.outgoing(db, record, wallet)
            self.settle(db, record, tip)
            self.bump(db, record, wallet, rate)
            self.build(db, record, wallet, rate)
            self.sweep(db, record, wallet, rate)
            self.send(db, record, policy, wallet)

    def wallet_for(self, db, record, policy) -> ClanWallet:
        wallet = self.wallets.get(record.id)
        if wallet is None:
            wallet = self.wallets[record.id] = ClanWallet(policy)
        highest = db.scalar(
            select(func.max(WalletAddress.address_index)).where(
                WalletAddress.wallet_id == record.id
            )
        )
        wallet.reveal_to(highest or 0)
        change = self.next_change_index(db, record) - 1
        if change >= 0:
            wallet.wallet.reveal_addresses_to(bdk.KeychainKind.INTERNAL, change)
        return wallet

    def next_change_index(self, db, record) -> int:
        """One past the highest change address used by this wallet's payouts or paid into."""
        used = db.scalar(
            select(func.max(WalletPayout.change_index)).where(WalletPayout.wallet_id == record.id)
        )
        paid_in = db.scalar(
            select(func.max(WalletPayout.destination_index)).where(
                WalletPayout.to_wallet_id == record.id
            )
        )
        return max(-1 if used is None else used, -1 if paid_in is None else paid_in) + 1

    def confirmations(self, state: TxState, tip: int) -> int:
        return tip - state.height + 1 if state.height is not None else 0

    # Money in ----------------------------------------------------------------------------

    def receipts(self, db, record, wallet, tip):
        addresses = {
            row.address_index: row
            for row in db.scalars(select(WalletAddress).where(WalletAddress.wallet_id == record.id))
        }
        seen = set()
        for canonical in wallet.wallet.transactions():
            tx = canonical.transaction
            txid = str(tx.compute_txid())
            for vout, output in enumerate(tx.output()):
                derivation = wallet.wallet.derivation_of_spk(output.script_pubkey)
                if derivation is None or derivation.keychain != bdk.KeychainKind.EXTERNAL:
                    continue
                row = addresses.get(derivation.index)
                # The web app stored the address; credit only what this wallet derives itself.
                if not row or row.address != wallet.address(derivation.index):
                    if row:
                        alarm(db, record, "address_mismatch", row.id, index=row.address_index)
                    continue
                receipt_id = f"{txid}:{vout}"
                seen.add(receipt_id)
                if not db.get(WalletReceipt, receipt_id):
                    db.add(
                        WalletReceipt(
                            id=receipt_id,
                            wallet_id=record.id,
                            address_id=row.id,
                            txid=txid,
                            vout=vout,
                            amount_sats=output.value.to_sat(),
                        )
                    )
        db.flush()
        for receipt in db.scalars(
            select(WalletReceipt).where(
                WalletReceipt.wallet_id == record.id,
                (WalletReceipt.status == "pending")
                | (
                    (WalletReceipt.status == "confirmed")
                    & (WalletReceipt.confirmations < REORG_DEPTH)
                )
                | ((WalletReceipt.status == "dropped") & WalletReceipt.id.in_(list(seen))),
            )
        ).all():
            state = self.chain.state(receipt.txid)
            depth = self.confirmations(state, tip)
            receipt.updated_at = now_iso()
            if receipt.status == "confirmed":
                if depth == 0:
                    alarm(db, record, "receipt_reorg", receipt.id, amount_sats=receipt.amount_sats)
                else:
                    receipt.confirmations, receipt.block_height = depth, state.height
                continue
            if not state.found:
                receipt.status, receipt.confirmations = "dropped", 0
                continue
            receipt.status, receipt.confirmations, receipt.block_height = (
                "pending",
                depth,
                state.height,
            )
            if self.kes_receipt(db, receipt):
                self.note_rate(receipt)
            if depth >= self.settings.clan_wallet_confirmations:
                self.credit(db, record, receipt)

    def kes_receipt(self, db, receipt) -> bool:
        """Whether a payment repays a grant whose debt is in KES."""
        address = db.get(WalletAddress, receipt.address_id)
        if address.purpose != "repayment":
            return False
        grant = db.get(Grant, address.grant_id)
        return bool(grant) and kes_debts.is_kes(grant)

    def note_rate(self, receipt):
        """Keep the KES rate from when the payment was first seen, once one is available."""
        if receipt.kes_per_btc is None and self.kes_rate is not None:
            receipt.kes_per_btc = self.kes_rate.text
            receipt.kes_rate_published_at = self.kes_rate.published_at
            receipt.kes_rate_seen_at = now_iso()

    def credit(self, db, record, receipt) -> bool:
        """Book a confirmed payment, exactly once, into the clan's ledger.

        A repayment of a KES debt needs the rate it was seen at. Without one it stays
        pending, uncredited, and is tried again next cycle: nothing is guessed.
        """
        address = db.get(WalletAddress, receipt.address_id)
        value = reconciled(db, record.clan_id)
        amount = receipt.amount_sats * 1000
        reference = "chain:" + receipt.id
        allocated = 0
        facts = {}
        person = address.user_id
        if address.purpose == "repayment":
            debt = db.scalar(
                select(Debt).where(Debt.grant_id == address.grant_id).with_for_update()
            )
            grant = db.get(Grant, address.grant_id)
            person = grant.beneficiary_id
            rate = None
            if receipt.kes_per_btc is not None:
                rate = kes_debts.Rate(Decimal(receipt.kes_per_btc), receipt.kes_rate_published_at)
            if debt and grant.clan_id == record.clan_id:
                if kes_debts.needs_rate(grant, debt) and rate is None:
                    receipt.credit_note = kes_debts.WAITING_FOR_RATE
                    return False
                allocated, facts = kes_debts.repay(
                    db, record.clan_id, grant, debt, amount, reference, rate
                )
                if "credited_kes_minor" in facts or "surplus_kes_minor" in facts:
                    receipt.kes_credited_minor = facts.get("credited_kes_minor", 0)
                    receipt.kes_surplus_minor = facts.get("surplus_kes_minor", 0)
                    receipt.kes_owed_after_minor = facts["owed_after_kes_minor"]
        event = {"repayment": "recovery_surplus", "grant_funding": "grant_funding"}
        ledger(
            db,
            record.clan_id,
            event.get(address.purpose, "contribution"),
            reference + ":capital",
            amount - allocated,
            "bitcoin_custody",
            "clan_capital",
        )
        value.balance_msat += amount
        receipt.status, receipt.credited_at = "confirmed", now_iso()
        receipt.credit_note = None
        db.add(
            AuditEvent(
                clan_id=record.clan_id,
                actor_id=actor(db, record.clan_id, person),
                event_type="treasury_settled",
                payload={
                    "method": "onchain",
                    "receipt_id": receipt.id,
                    "purpose": address.purpose,
                    "grant_id": address.grant_id,
                    "amount_msat": str(amount),
                    "recovery_msat": str(allocated),
                    **facts,
                },
            )
        )
        return True

    # Money out ---------------------------------------------------------------------------

    def payouts(self, db, record, statuses):
        return db.scalars(
            select(WalletPayout)
            .where(WalletPayout.wallet_id == record.id, WalletPayout.status.in_(statuses))
            .order_by(WalletPayout.created_at)
        ).all()

    def went_out(self, db, record, payout):
        """A payout is on the network. Other versions spending the same coins can't confirm."""
        if payout.status != "broadcast":
            payout.status, payout.broadcast_at = "broadcast", payout.broadcast_at or now_iso()
            payout.updated_at = now_iso()
            for item in payout.recipients:
                grant = db.get(Grant, item["grant_id"])
                if grant.status == "awaiting_signatures":
                    grant.status = "paying"
        spent = set(payout.inputs)
        for other in self.payouts(db, record, LIVE_PAYOUT_STATUSES):
            if other.id == payout.id or not spent & set(other.inputs):
                continue
            if other.status == "awaiting_signatures" and other.replaces == payout.id:
                continue  # a higher-fee version of this payout, which can still replace it
            other.status, other.updated_at = "replaced", now_iso()
            other.replaced_by = other.replaced_by or payout.id
            self.release(db, other, payout)

    def release(self, db, other, payout):
        """Grants in `other` that `payout` doesn't pay need a new payout built."""
        paid = {item["grant_id"] for item in payout.recipients}
        for item in other.recipients:
            request = db.get(WalletPayoutRequest, item["grant_id"])
            if item["grant_id"] not in paid and request and request.status == "drafted":
                request.status, request.updated_at = "waiting", now_iso()

    def outgoing(self, db, record, wallet):
        for canonical in wallet.wallet.transactions():
            tx = canonical.transaction
            if wallet.wallet.sent_and_received(tx).sent.to_sat() == 0:
                continue
            txid = str(tx.compute_txid())
            payout = db.scalar(select(WalletPayout).where(WalletPayout.txid == txid))
            if payout is None or payout.wallet_id != record.id:
                alarm(db, record, "unapproved_spend", txid)
            elif payout.status != "confirmed":
                self.went_out(db, record, payout)

    def settle(self, db, record, tip):
        for payout in self.payouts(db, record, ["broadcast", "confirmed"]):
            if payout.status == "confirmed" and payout.confirmations >= REORG_DEPTH:
                continue
            state = self.chain.state(payout.txid)
            depth = self.confirmations(state, tip)
            if payout.status == "confirmed":
                if depth == 0:
                    alarm(db, record, "payout_reorg", payout.id, txid=payout.txid)
                else:
                    payout.confirmations, payout.block_height = depth, state.height
                continue
            payout.confirmations, payout.block_height = depth, state.height
            if not state.found and payout.raw_tx:
                # Never reset a sent payout. Broadcasting the same transaction again is safe.
                try:
                    self.chain.broadcast(payout.raw_tx)
                    payout.last_error = None
                except Exception:
                    payout.last_error = "rebroadcast_failed"
            if depth >= self.settings.clan_wallet_confirmations:
                self.book(db, record, payout)

    def book(self, db, record, payout):
        """Record a confirmed payout: the grants are disbursed and their debts start.

        A refresh or move only costs the clan its network fee. The coins stay the clan's.
        """
        value = reconciled(db, record.clan_id)
        if payout.kind != "grant":
            fee = payout.fee_sats * 1000
            if value.balance_msat - value.reserved_msat < fee:
                alarm(db, record, "payout_accounting", payout.id, kind=payout.kind)
                return
            value.balance_msat -= fee
            ledger(
                db,
                record.clan_id,
                "network_fee",
                f"chain-payout:{payout.txid}:fee",
                fee,
                "network_fees",
                "bitcoin_custody",
            )
            target = db.get(ClanWalletRecord, payout.to_wallet_id)
            db.add(
                AuditEvent(
                    clan_id=record.clan_id,
                    actor_id=actor(db, record.clan_id),
                    event_type="wallet_moved" if payout.kind == "move" else "wallet_refreshed",
                    payload={
                        "source": "chain_watcher",
                        "payout_id": payout.id,
                        "txid": payout.txid,
                        "from_generation": record.generation,
                        "to_generation": target.generation,
                        "fee_sats": payout.fee_sats,
                    },
                )
            )
        for item in payout.recipients:
            grant = db.get(Grant, item["grant_id"])
            request = db.get(WalletPayoutRequest, grant.id)
            amount = item["approved_sats"] * 1000
            reserved = request.reserved_sats * 1000
            if (
                db.get(Debt, grant.id)
                or value.reserved_msat < reserved
                or value.balance_msat < amount
            ):
                alarm(db, record, "payout_accounting", payout.id, grant_id=grant.id)
                return
            value.reserved_msat -= reserved
            value.balance_msat -= amount
            ledger(
                db,
                record.clan_id,
                "grant_disbursed",
                f"chain-payout:{payout.txid}:{grant.id}",
                amount,
                "grant_receivable",
                "bitcoin_custody",
            )
            db.add(Debt(grant_id=grant.id, principal_msat=amount, outstanding_msat=amount))
            # The member now owes the grant: KES cents for a KES debt, else sats.
            in_kes = kes_debts.is_kes(grant)
            grant.outstanding_minor = grant.principal_minor if in_kes else grant.amount_sats
            grant.status = "in_recovery"
            request.status, request.updated_at = "paid", now_iso()
            db.add(
                AuditEvent(
                    clan_id=record.clan_id,
                    actor_id=grant.beneficiary_id,
                    event_type="grant_disbursed",
                    payload={
                        "method": "onchain",
                        "grant_id": grant.id,
                        "txid": payout.txid,
                        "amount_msat": str(amount),
                        "received_sats": item["received_sats"],
                        "network_fee_paid_by": payout.fee_paid_by,
                        **({"debt_kes_minor": grant.principal_minor} if in_kes else {}),
                    },
                )
            )
        payout.status, payout.updated_at = "confirmed", now_iso()
        # Versions still waiting for signatures can never confirm now.
        spent = set(payout.inputs)
        for other in self.payouts(db, record, ["awaiting_signatures"]):
            if spent & set(other.inputs):
                other.status, other.updated_at = "replaced", now_iso()
                other.replaced_by = other.replaced_by or payout.id
                self.release(db, other, payout)

    def spendable(self, db, record, wallet) -> list[int]:
        """Coins no payout is spending, largest first: what the fee preview counts."""
        busy = set()
        for payout in self.payouts(db, record, LIVE_PAYOUT_STATUSES):
            busy |= set(payout.inputs)
        values = [
            utxo.txout.value.to_sat()
            for utxo in wallet.wallet.list_unspent()
            if outpoint_text(utxo.outpoint) not in busy
        ]
        return sorted(values, reverse=True)[:MAX_PREVIEW_COINS]

    def bump(self, db, record, wallet, rate):
        """Offer a higher-fee version of a sent payout that hasn't confirmed in time.

        The new version spends the same coins, so only one can confirm. It needs fresh
        signatures from the clan and Afribit: nothing is resent with a new fee silently.
        """
        waited = timedelta(minutes=self.settings.clan_wallet_bump_after_minutes)
        cutoff = (datetime.now(UTC) - waited).isoformat()
        waiting = self.payouts(db, record, ["awaiting_signatures"])
        for payout in self.payouts(db, record, ["broadcast"]):
            if payout.confirmations or not payout.raw_tx or (payout.broadcast_at or "") > cutoff:
                continue
            if any(other.replaces == payout.id for other in waiting):
                continue
            # Fees haven't risen and the network still has it: give it more time.
            old_rate = payout_rate(payout)
            if rate <= old_rate and payout.last_error != "rebroadcast_failed":
                continue
            size = bdk.Transaction(bytes.fromhex(payout.raw_tx)).vsize()
            # Network rule for replacements: pay the old fee plus 1 sat for each vbyte.
            new_rate = max(rate, old_rate + 1, (payout.fee_sats + size) / size)
            recipients = [Recipient(r["address"], r["approved_sats"]) for r in payout.recipients]
            limit = self.fee_limit(payout.kind)
            try:
                if payout.kind == "grant":
                    built = wallet.build_replacement(
                        payout.psbt,
                        recipients,
                        fee_rate_sat_vb=new_rate,
                        max_fee_sats=limit,
                        fee_paid_by=payout.fee_paid_by,
                    )
                    paid = [
                        {**item, "received_sats": out.amount_sats}
                        for item, out in zip(payout.recipients, built.received, strict=True)
                    ]
                else:
                    built = wallet.build_sweep_replacement(
                        payout.psbt,
                        self.destination(db, payout),
                        fee_rate_sat_vb=new_rate,
                        max_fee_sats=limit,
                    )
                    paid = []
                if built.fee_sats < payout.fee_sats + size:
                    raise ClanWalletError("The new fee is too small to replace the payment")
            except ClanWalletError as exc:
                payout.last_error = ("no_higher_fee: " + str(exc))[:100]
                continue
            replacement = WalletPayout(
                wallet_id=record.id,
                clan_id=record.clan_id,
                kind=payout.kind,
                psbt=built.psbt,
                txid=built.txid,
                inputs=payout.inputs,
                change_index=payout.change_index,
                fee_sats=built.fee_sats,
                max_fee_sats=limit,
                **rate_columns(new_rate),
                fee_paid_by=payout.fee_paid_by,
                recipients=paid,
                to_wallet_id=payout.to_wallet_id,
                destination_index=payout.destination_index,
                destination_address=payout.destination_address,
                replaces=payout.id,
            )
            db.add(replacement)
            db.flush()
            db.add(
                AuditEvent(
                    clan_id=record.clan_id,
                    actor_id=actor(db, record.clan_id),
                    event_type="payout_fee_raised",
                    payload={
                        "source": "chain_watcher",
                        "payout_id": replacement.id,
                        "replaces": payout.id,
                        "txid": replacement.txid,
                        "fee_sats": replacement.fee_sats,
                        "previous_fee_sats": payout.fee_sats,
                    },
                )
            )

    def build(self, db, record, wallet, rate):
        for request in db.scalars(
            select(WalletPayoutRequest).where(
                WalletPayoutRequest.wallet_id == record.id,
                WalletPayoutRequest.status == "waiting",
            )
        ).all():
            grant = db.get(Grant, request.grant_id)
            if grant.status != "awaiting_signatures":
                request.last_error = "grant_not_payable"
                continue
            if record.status == "retired":
                # Paid from the newest wallet once the coins have moved across.
                newest = active_wallet(db, record.clan_id)
                if newest and newest.generation > record.generation:
                    request.wallet_id, request.updated_at = newest.id, now_iso()
                    continue
            prior = [
                p
                for p in self.payouts(db, record, LIVE_PAYOUT_STATUSES)
                if any(r["grant_id"] == grant.id for r in p.recipients)
            ]
            if any(p.status == "broadcast" for p in prior):
                continue
            # A new version must spend the same coins as any earlier one, so at most one of
            # them can ever confirm, even if someone kept a fully signed copy.
            reuse = next(
                (
                    p.inputs
                    for p in prior
                    if all(wallet.wallet.get_utxo(outpoint(i)) for i in p.inputs)
                ),
                None,
            )
            try:
                payout = self.draft(db, record, wallet, rate, request, grant, reuse, prior)
            except ClanWalletError as exc:
                request.last_error = str(exc)[:100]
                continue
            for earlier in prior:
                earlier.status, earlier.replaced_by = "expired", payout.id
                earlier.updated_at = now_iso()
            payout.replaces = prior[-1].id if prior else None
            request.status, request.last_error = "drafted", None
            request.updated_at = now_iso()
            db.add(
                AuditEvent(
                    clan_id=record.clan_id,
                    actor_id=grant.beneficiary_id,
                    event_type="payout_built",
                    payload={
                        "payout_id": payout.id,
                        "grant_id": grant.id,
                        "txid": payout.txid,
                        "fee_sats": payout.fee_sats,
                        "replaces": payout.replaces,
                    },
                )
            )

    def draft(self, db, record, wallet, rate, request, grant, reuse, prior):
        # A grant payout may take coins from a refresh still waiting for signatures; the
        # refresh is then dropped and built again from the coins left.
        refreshes = [
            other
            for other in self.payouts(db, record, ["awaiting_signatures"])
            if other.kind == "refresh"
        ]
        busy = set()
        for other in self.payouts(db, record, LIVE_PAYOUT_STATUSES):
            if other not in prior and other not in refreshes:
                busy |= set(other.inputs)
        locked = []
        if reuse is None:
            # Only coins with 3 confirmations that no other payout is spending.
            for utxo in wallet.wallet.list_unspent():
                name = outpoint_text(utxo.outpoint)
                state = self.chain.state(str(utxo.outpoint.txid))
                if (
                    name in busy
                    or self.confirmations(state, self.tip) < self.settings.clan_wallet_confirmations
                ):
                    wallet.wallet.lock_outpoint(utxo.outpoint)
                    locked.append(utxo.outpoint)
        try:
            built = wallet.build_payout(
                [Recipient(request.address, grant.amount_sats)],
                fee_rate_sat_vb=rate,
                max_fee_sats=self.settings.clan_wallet_max_fee_sats,
                fee_paid_by="recipients",
                allow_unconfirmed=True,
                utxos=[outpoint(i) for i in reuse] if reuse else None,
            )
        finally:
            for item in locked:
                wallet.wallet.unlock_outpoint(item)
        psbt = bdk.Psbt(built.psbt)
        tx = psbt.extract_tx_unchecked_fee_rate()
        change = None
        for output in tx.output():
            derivation = wallet.wallet.derivation_of_spk(output.script_pubkey)
            if derivation is not None and derivation.keychain == bdk.KeychainKind.INTERNAL:
                change = derivation.index
        if change is not None and change >= MAX_CHANGE_INDEX:
            raise ClanWalletError(
                "This wallet has used all its change addresses. Move the clan to a new wallet."
            )
        beneficiary = db.get(User, grant.beneficiary_id)
        received = built.received[0]
        payout = WalletPayout(
            wallet_id=record.id,
            clan_id=record.clan_id,
            psbt=built.psbt,
            txid=built.txid,
            inputs=sorted(outpoint_text(item.previous_output) for item in tx.input()),
            change_index=change,
            fee_sats=built.fee_sats,
            max_fee_sats=self.settings.clan_wallet_max_fee_sats,
            **rate_columns(rate),
            fee_paid_by="recipients",
            recipients=[
                {
                    "grant_id": grant.id,
                    "name": beneficiary.display_name,
                    "address": request.address,
                    "approved_sats": grant.amount_sats,
                    "received_sats": received.amount_sats,
                }
            ],
        )
        db.add(payout)
        db.flush()
        for other in refreshes:
            if set(other.inputs) & set(payout.inputs):
                other.status, other.updated_at = "expired", now_iso()
        return payout

    # Refreshes and moves ---------------------------------------------------------------

    def fee_limit(self, kind: str) -> int:
        if kind == "grant":
            return self.settings.clan_wallet_max_fee_sats
        return self.settings.clan_wallet_max_sweep_fee_sats

    def destination(self, db, payout) -> str:
        """The change address a refresh or move pays, derived again from the target wallet."""
        target = db.get(ClanWalletRecord, payout.to_wallet_id)
        if target.clan_id != payout.clan_id or target.activated_at is None:
            raise ClanWalletError("The payment goes to a wallet that isn't the clan's")
        address = ClanWallet(record_policy(db, target)).change_address(payout.destination_index)
        if address != payout.destination_address:
            raise ClanWalletError("The stored destination doesn't match the clan wallet")
        return address

    def sweep(self, db, record, wallet, rate):
        """Build a refresh or a move when one is due. Grant payouts go first.

        - A retired wallet moves its coins to the clan's newest wallet once no grant is
          still being paid from it.
        - An active wallet refreshes its coins before the recovery wait nears its end. Until
          then only the normal path (the clan and Afribit together) can spend them.
        Both pay one change address of the target wallet and need the usual signatures.
        """
        live = self.payouts(db, record, LIVE_PAYOUT_STATUSES)
        if any(payout.kind != "grant" for payout in live):
            return
        if record.status == "retired":
            target, kind = active_wallet(db, record.clan_id), "move"
            pending = db.scalar(
                select(WalletPayoutRequest.grant_id).where(
                    WalletPayoutRequest.wallet_id == record.id,
                    WalletPayoutRequest.status != "paid",
                )
            )
            if not target or target.generation <= record.generation or live or pending:
                return
        else:
            target, kind = record, "refresh"
        busy = set()
        for payout in live:
            busy |= set(payout.inputs)
        coins = []
        for utxo in wallet.wallet.list_unspent():
            name = outpoint_text(utxo.outpoint)
            depth = self.confirmations(self.chain.state(str(utxo.outpoint.txid)), self.tip)
            if depth >= record.recovery_blocks:
                # The signatories could now spend this coin without Afribit.
                alarm(db, record, "recovery_path_open", name, confirmations=depth)
            if name not in busy and depth >= self.settings.clan_wallet_confirmations:
                coins.append((depth, name, utxo.outpoint))
        if not coins:
            return
        coins.sort(key=lambda coin: (-coin[0], coin[1]))
        due = record.recovery_blocks - record.recovery_blocks // REFRESH_MARGIN
        if kind == "refresh" and coins[0][0] < due:
            return
        index = self.next_change_index(db, target)
        if kind == "refresh":
            address = wallet.change_address(index)
        else:
            address = ClanWallet(record_policy(db, target)).change_address(index)
        limit = self.fee_limit(kind)
        chosen, built = coins[:MAX_SWEEP_COINS], None
        while chosen:
            try:
                built = wallet.build_sweep(
                    [coin[2] for coin in chosen],
                    address,
                    fee_rate_sat_vb=rate,
                    max_fee_sats=limit,
                )
                break
            except ClanWalletError:
                chosen = chosen[: len(chosen) // 2]
        value = reconciled(db, record.clan_id)
        if built is None or value.balance_msat - value.reserved_msat < built.fee_sats * 1000:
            # Once a day at most. Usually fees are high for now; it is tried again each cycle.
            alarm(db, record, "sweep_blocked", f"{record.id}:{kind}:{self.tip // BLOCKS_PER_DAY}")
            return
        payout = WalletPayout(
            wallet_id=record.id,
            clan_id=record.clan_id,
            kind=kind,
            psbt=built.psbt,
            txid=built.txid,
            inputs=sorted(coin[1] for coin in chosen),
            change_index=index if kind == "refresh" else None,
            fee_sats=built.fee_sats,
            max_fee_sats=limit,
            **rate_columns(rate),
            fee_paid_by="clan",
            recipients=[],
            to_wallet_id=target.id,
            destination_index=index,
            destination_address=address,
        )
        db.add(payout)
        db.flush()
        db.add(
            AuditEvent(
                clan_id=record.clan_id,
                actor_id=actor(db, record.clan_id),
                event_type="wallet_move_built" if kind == "move" else "wallet_refresh_built",
                payload={
                    "source": "chain_watcher",
                    "payout_id": payout.id,
                    "txid": payout.txid,
                    "from_generation": record.generation,
                    "to_generation": target.generation,
                    "amount_sats": built.amount_sats,
                    "fee_sats": built.fee_sats,
                    "coins": len(chosen),
                },
            )
        )

    def send(self, db, record, policy, wallet):
        for payout in self.payouts(db, record, ["awaiting_signatures"]):
            signed = signatures(db, payout)
            if len(signed.signers) < policy.threshold or not signed.oversight:
                continue
            recipients = [Recipient(r["address"], r["approved_sats"]) for r in payout.recipients]
            try:
                if payout.kind == "grant":
                    result = wallet.finalize(
                        payout.psbt,
                        [row.psbt for row in signed.rows],
                        recipients,
                        max_fee_sats=payout.max_fee_sats,
                        fee_paid_by=payout.fee_paid_by,
                    )
                else:
                    result = wallet.finalize_sweep(
                        payout.psbt,
                        [row.psbt for row in signed.rows],
                        self.destination(db, payout),
                        max_fee_sats=payout.max_fee_sats,
                    )
            except SignatureError as exc:
                origins = key_origins(psbt_details(payout.psbt))
                bad = {origins[key][0] for key in exc.bad_keys if key in origins}
                for row in signed.rows:
                    if row.fingerprint in bad:
                        row.invalid_at = now_iso()
                        alarm(
                            db,
                            record,
                            "invalid_signature",
                            f"{payout.id}:{row.fingerprint}:{row.created_at}",
                            role=row.role,
                            signer_id=row.user_id,
                        )
                payout.last_error = "invalid_signature" if bad else "could_not_finish"
                continue
            except ClanWalletError as exc:
                payout.last_error = str(exc)[:100]
                continue
            try:
                self.chain.broadcast(result.raw_hex)
            except Exception:
                payout.last_error = "broadcast_failed"
                continue
            payout.raw_tx, payout.last_error = result.raw_hex, None
            self.went_out(db, record, payout)
            db.add(
                AuditEvent(
                    clan_id=record.clan_id,
                    actor_id=(
                        db.get(Grant, payout.recipients[0]["grant_id"]).beneficiary_id
                        if payout.recipients
                        else actor(db, record.clan_id)
                    ),
                    event_type="payout_broadcast",
                    payload={
                        "source": "chain_watcher",
                        "payout_id": payout.id,
                        "txid": payout.txid,
                    },
                )
            )


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    watcher = ChainWatcher(LiveSettings())
    postgres = watcher.security.engine.dialect.name == "postgresql"
    failed = 0
    while True:
        with watcher.security.engine.connect() as connection:
            if (
                postgres
                and not connection.execute(text(f"SELECT pg_try_advisory_lock({LOCK_ID})")).scalar()
            ):
                # Another watcher is running. Only one may build and broadcast.
                time.sleep(INTERVAL_SECONDS)
                continue
            try:
                watcher.tick()
                # Every wallet failing usually means the explorer is refusing us too.
                everything_failed = watcher.watched and len(watcher.failures) == watcher.watched
                failed = failed + 1 if everything_failed else 0
            except Exception as exc:
                failed += 1
                # No PSBT, address or key material is logged.
                print(f"Chain watcher cycle interrupted: {type(exc).__name__}", flush=True)
            finally:
                if postgres:
                    connection.execute(text(f"SELECT pg_advisory_unlock({LOCK_ID})"))
                    connection.commit()
        if args.once:
            break
        if failed:
            print(f"Chain watcher waits {next_delay(failed)} seconds before trying again.")
        time.sleep(next_delay(failed))


if __name__ == "__main__":
    main()
