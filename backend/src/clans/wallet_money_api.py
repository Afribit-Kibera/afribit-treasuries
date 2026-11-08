"""Clan wallet money routes: addresses, beneficiary payout addresses, receipts, payouts and
signatures. See docs/clan-wallet-api.md.

The web app never credits money or builds payments. It derives addresses from the public
wallet, holds back the grant amount from the confirmed balance, and stores signed copies.
The chain watcher checks every signature with BDK before anything is broadcast.
"""

import math
from datetime import UTC, datetime, timedelta

import bdkpython as bdk
from fastapi import HTTPException, Query, Request, Response
from pydantic import Field
from sqlalchemy import func, select

from clans import communities, reports
from clans.clan_wallet import (
    MAINNET,
    MIN_PAYOUT_SATS,
    NETWORKS,
    SAT_KWU_PER_SAT_VB,
    ClanWallet,
    ClanWalletError,
    SignerKey,
)
from clans.live_app import Input, audit, lock_clan, membership
from clans.live_models import Grant
from clans.models import now_iso
from clans.money_service import reconciled
from clans.wallet_alarms import alarm_views, with_clan_names
from clans.wallet_api import active_wallet, policy_view, wallet_keys
from clans.wallet_models import (
    ADDRESS_PURPOSES,
    ChainStatus,
    ClanWalletRecord,
    WalletAddress,
    WalletPayout,
    WalletPayoutRequest,
    WalletReceipt,
    WalletSignerKey,
)
from clans.wallet_payments import (
    accept_signature,
    actor,
    payout_view,
    record_policy,
    signatures,
)

# Fee quotes need a recent view of the network from the chain watcher.
CHAIN_STATUS_MAX_AGE = timedelta(minutes=10)
PAYABLE_GRANT_STATUSES = {"awaiting_funding", "awaiting_signatures"}
RECEIPT_LIMIT = 50


class AddressInput(Input):
    address: str = Field(min_length=14, max_length=100)


class SignatureInput(Input):
    psbt: str = Field(min_length=20, max_length=400_000)


class OversightSignatureInput(SignatureInput):
    """The oversight tool's signed file, uploaded as it is."""

    id: str | None = Field(default=None, max_length=36)
    clan_id: str | None = Field(default=None, max_length=36)
    txid: str | None = Field(default=None, max_length=64)


def receipt_view(receipt, address):
    return {
        "id": receipt.id,
        "txid": receipt.txid,
        "vout": receipt.vout,
        "address": address.address,
        "purpose": address.purpose,
        "grant_id": address.grant_id,
        "amount_sats": receipt.amount_sats,
        "confirmations": receipt.confirmations,
        "status": receipt.status,
        # Repayments of a KES debt: the rate used and the KES counted, once credited.
        "kes_per_btc": receipt.kes_per_btc,
        "kes_credited_minor": receipt.kes_credited_minor,
        "kes_owed_after_minor": receipt.kes_owed_after_minor,
        # Why a confirmed payment isn't counted yet: "waiting_for_rate", or null.
        "credit_note": receipt.credit_note,
    }


def address_view(row):
    return {
        "address": row.address,
        "keychain": "external",
        "index": row.address_index,
        "purpose": row.purpose,
        "grant_id": row.grant_id,
    }


def install(app, security, settings):
    def require_enabled():
        if not settings.clan_wallets_enabled:
            raise HTTPException(503, "Clan wallets are not available yet.")

    def active(db, clan_id):
        record = active_wallet(db, clan_id)
        if not record:
            raise HTTPException(409, "The clan wallet isn't active yet.")
        try:
            return record, record_policy(db, record)
        except ClanWalletError as exc:
            raise HTTPException(409, str(exc)) from exc

    def paying_wallet(db, payout):
        """The wallet a payout spends from: the active one, or a retired one being emptied."""
        record = db.get(ClanWalletRecord, payout.wallet_id)
        if record.activated_at is None or record.status not in {"active", "retired"}:
            raise HTTPException(409, "This payout's wallet isn't in use.")
        try:
            return record, record_policy(db, record)
        except ClanWalletError as exc:
            raise HTTPException(409, str(exc)) from exc

    def clan_wallet_ids(db, clan_id):
        return select(ClanWalletRecord.id).where(ClanWalletRecord.clan_id == clan_id)

    def fee_rate(db, network):
        status = db.get(ChainStatus, network)
        cutoff = (datetime.now(UTC) - CHAIN_STATUS_MAX_AGE).isoformat()
        if not status or status.observed_at < cutoff:
            raise HTTPException(
                503, "Bitcoin network information is unavailable. Try again shortly."
            )
        if status.fee_rate_sat_kwu:
            return status.fee_rate_sat_kwu / SAT_KWU_PER_SAT_VB
        return float(status.fee_rate_sat_vb)

    def coins_needed(coins, amount_sats, rate, policy):
        """How many coins the payout will spend. Payouts take the largest coins first."""
        total = 0
        for count, value in enumerate(coins or [], start=1):
            total += value
            if total >= amount_sats + rate * policy.estimated_payout_vbytes(count):
                return count
        return max(len(coins or []), 1)

    def beneficiary_grant(db, clan_id, grant_id, user_id):
        grant = db.get(Grant, grant_id)
        if not grant or grant.clan_id != clan_id:
            raise HTTPException(404, "Grant not found.")
        if grant.beneficiary_id != user_id:
            raise HTTPException(403, "Only the beneficiary can give the payout address.")
        if not grant.accepted_at or grant.status not in PAYABLE_GRANT_STATUSES:
            raise HTTPException(409, "The grant must pass the member vote and be accepted first.")
        return grant

    def payout_address(db, record, policy, value):
        address = value.strip()
        start = "bc1" if record.network == MAINNET else "tb1"
        if not address.lower().startswith(start):
            kind = "a Bitcoin" if record.network == MAINNET else "a test-network Bitcoin"
            raise HTTPException(400, f"Use {kind} address that starts with {start}q or {start}p.")
        address = address.lower()
        try:
            script = bdk.Address(address, NETWORKS[record.network]).script_pubkey()
        except Exception as exc:
            raise HTTPException(400, "This address isn't valid on the clan's network.") from exc
        if db.scalar(select(WalletAddress.id).where(WalletAddress.address == address)) or (
            ClanWallet(policy).wallet.is_mine(script)
        ):
            raise HTTPException(
                400, "Use an address from your own wallet, not one of the clan's addresses."
            )
        return address

    def preview(db, record, policy, grant, address):
        rate = fee_rate(db, record.network)
        coins = coins_needed(record.spendable_coins, grant.amount_sats, rate, policy)
        fee = math.ceil(rate * policy.estimated_payout_vbytes(coins))
        if fee > settings.clan_wallet_max_fee_sats:
            raise HTTPException(409, "Network fees are unusually high. Try again later.")
        if grant.amount_sats - fee < MIN_PAYOUT_SATS:
            raise HTTPException(409, "The network fee would leave you with too little.")
        return {
            "address": address,
            "approved_sats": grant.amount_sats,
            "fee_paid_by": "recipients",
            "estimated_fee_sats": fee,
            "estimated_received_sats": grant.amount_sats - fee,
            "fee_rate_sat_vb": rate,
        }

    def sent_already(db, clan_id, grant_id):
        for payout in db.scalars(
            select(WalletPayout).where(
                WalletPayout.clan_id == clan_id,
                WalletPayout.status.in_(["broadcast", "confirmed"]),
            )
        ):
            if any(r["grant_id"] == grant_id for r in payout.recipients):
                return True
        return False

    @app.get("/api/clans/{clan_id}/wallet/address")
    def get_address(clan_id: str, purpose: str, request: Request, grant_id: str | None = None):
        require_enabled()
        if purpose not in ADDRESS_PURPOSES:
            raise HTTPException(422, "Unknown address purpose.")
        if (purpose == "repayment") != bool(grant_id):
            raise HTTPException(422, "A grant is needed for repayments, and only for them.")
        security.limit(request, "wallet-address", 60, 3600)
        with security.db() as db:
            user = security.current(request, db)
            lock_clan(db, clan_id)
            membership(db, clan_id, user.id)
            record, policy = active(db, clan_id)
            if purpose == "repayment":
                grant = db.get(Grant, grant_id)
                if not grant or grant.clan_id != clan_id or grant.status != "in_recovery":
                    raise HTTPException(409, "This grant has no outstanding repayment.")
            query = select(WalletAddress).where(
                WalletAddress.wallet_id == record.id, WalletAddress.purpose == purpose
            )
            if purpose == "repayment":
                query = query.where(WalletAddress.grant_id == grant_id)
            elif purpose == "contribution":
                query = query.where(WalletAddress.user_id == user.id)
            row = db.scalar(query)
            if not row:
                if purpose == "grant_funding":
                    index = 0
                else:
                    highest = db.scalar(
                        select(func.max(WalletAddress.address_index)).where(
                            WalletAddress.wallet_id == record.id
                        )
                    )
                    index = max(highest or 0, 0) + 1
                row = WalletAddress(
                    wallet_id=record.id,
                    address_index=index,
                    address=ClanWallet(policy).address(index),
                    purpose=purpose,
                    grant_id=grant_id,
                    user_id=user.id if purpose == "contribution" else None,
                )
                db.add(row)
                db.flush()
            return address_view(row)

    @app.get("/api/clans/{clan_id}/grants/{grant_id}/payout-quote")
    def payout_quote(clan_id: str, grant_id: str, address: str, request: Request):
        require_enabled()
        with security.db() as db:
            user = security.current(request, db)
            membership(db, clan_id, user.id)
            record, policy = active(db, clan_id)
            grant = beneficiary_grant(db, clan_id, grant_id, user.id)
            return preview(db, record, policy, grant, payout_address(db, record, policy, address))

    @app.post("/api/clans/{clan_id}/grants/{grant_id}/payout-address")
    def set_payout_address(clan_id: str, grant_id: str, data: AddressInput, request: Request):
        require_enabled()
        security.limit(request, "payout-address", 20, 3600)
        with security.db() as db:
            user = security.current(request, db)
            lock_clan(db, clan_id)
            membership(db, clan_id, user.id)
            from clans.access_service import recovery_hold

            if recovery_hold(db, user.id):
                raise HTTPException(
                    409,
                    "An account recovery is waiting. "
                    "Block it or finish it before changing a payment.",
                )
            record, policy = active(db, clan_id)
            grant = beneficiary_grant(db, clan_id, grant_id, user.id)
            address = payout_address(db, record, policy, data.address)
            quote = preview(db, record, policy, grant, address)
            if sent_already(db, clan_id, grant_id):
                raise HTTPException(409, "This grant has already been sent.")
            existing = db.get(WalletPayoutRequest, grant_id)
            if existing:
                # It may still be on a retired wallet; the chain watcher moves it across.
                if existing.status == "paid":
                    raise HTTPException(409, "This grant has already been sent.")
                if existing.address != address:
                    previous = existing.address
                    existing.address, existing.status = address, "waiting"
                    existing.last_error, existing.updated_at = None, now_iso()
                    audit(
                        db,
                        clan_id,
                        user.id,
                        "payout_address_changed",
                        grant_id=grant_id,
                        previous=previous,
                        address=address,
                    )
                return quote
            value = reconciled(db, clan_id)
            amount_msat = grant.amount_sats * 1000
            if value.balance_msat - value.reserved_msat < amount_msat:
                raise HTTPException(409, "The clan needs enough confirmed money for this grant.")
            value.reserved_msat += amount_msat
            db.add(
                WalletPayoutRequest(
                    grant_id=grant_id,
                    wallet_id=record.id,
                    address=address,
                    reserved_sats=grant.amount_sats,
                )
            )
            grant.status = "awaiting_signatures"
            audit(
                db,
                clan_id,
                user.id,
                "payout_address_given",
                grant_id=grant_id,
                address=address,
                amount_sats=grant.amount_sats,
            )
            return quote

    @app.get("/api/clans/{clan_id}/wallet/receipts")
    def receipts(clan_id: str, request: Request, address: str | None = None):
        with security.db() as db:
            user = security.current(request, db)
            membership(db, clan_id, user.id)
            # Every generation: a late payment to an old address is still the clan's.
            query = select(WalletAddress).where(
                WalletAddress.wallet_id.in_(clan_wallet_ids(db, clan_id))
            )
            if address:
                rows = db.scalars(query.where(WalletAddress.address == address.strip().lower()))
            else:
                mine = select(Grant.id).where(Grant.beneficiary_id == user.id)
                rows = db.scalars(
                    query.where(
                        (WalletAddress.user_id == user.id) | (WalletAddress.grant_id.in_(mine))
                    )
                )
            addresses = {row.id: row for row in rows}
            found = db.scalars(
                select(WalletReceipt)
                .where(WalletReceipt.address_id.in_(list(addresses)))
                .order_by(WalletReceipt.first_seen_at.desc(), WalletReceipt.id)
                .limit(RECEIPT_LIMIT)
            )
            return [receipt_view(item, addresses[item.address_id]) for item in found]

    def visible_payout(db, clan_id, payout_id):
        payout = db.get(WalletPayout, payout_id)
        if not payout or payout.clan_id != clan_id:
            raise HTTPException(404, "Payout not found.")
        return payout

    @app.get("/api/clans/{clan_id}/wallet/payouts")
    def list_payouts(
        clan_id: str, request: Request, status: str | None = None, grant_id: str | None = None
    ):
        with security.db() as db:
            user = security.current(request, db)
            membership(db, clan_id, user.id)
            wanted = {part.strip() for part in status.split(",")} if status else None
            views, policies = [], {}
            for payout in db.scalars(
                select(WalletPayout)
                .where(WalletPayout.clan_id == clan_id)
                .order_by(WalletPayout.created_at.desc())
                .limit(100)
            ):
                if grant_id and not any(r["grant_id"] == grant_id for r in payout.recipients):
                    continue
                if payout.wallet_id not in policies:
                    try:
                        policies[payout.wallet_id] = paying_wallet(db, payout)[1]
                    except HTTPException:
                        policies[payout.wallet_id] = None
                if policies[payout.wallet_id] is None:
                    continue
                view = payout_view(db, payout, policies[payout.wallet_id], user.id)
                if wanted is None or view["status"] in wanted:
                    views.append(view)
            return views

    @app.get("/api/clans/{clan_id}/wallet/payouts/{payout_id}")
    def get_payout(clan_id: str, payout_id: str, request: Request):
        with security.db() as db:
            user = security.current(request, db)
            membership(db, clan_id, user.id)
            payout = visible_payout(db, clan_id, payout_id)
            policy = record_policy(db, db.get(ClanWalletRecord, payout.wallet_id))
            return payout_view(db, payout, policy, user.id)

    def signable(db, payout):
        if payout.status in {"replaced", "expired"}:
            raise HTTPException(409, "This payout was replaced. Sign the newest version.")
        if payout.status != "awaiting_signatures":
            raise HTTPException(409, "This payout has already been sent.")

    @app.post("/api/clans/{clan_id}/wallet/payouts/{payout_id}/signature")
    def sign_payout(clan_id: str, payout_id: str, data: SignatureInput, request: Request):
        require_enabled()
        security.limit(request, "payout-signature", 60, 3600)
        with security.db() as db:
            user = security.current(request, db)
            lock_clan(db, clan_id)
            member = membership(db, clan_id, user.id)
            payout = visible_payout(db, clan_id, payout_id)
            record, policy = paying_wallet(db, payout)
            signable(db, payout)
            key = db.scalar(
                select(WalletSignerKey).where(
                    WalletSignerKey.wallet_id == record.id, WalletSignerKey.user_id == user.id
                )
            )
            if not member.is_signer or not key:
                raise HTTPException(403, "Only the clan's signatories sign payouts.")
            beneficiaries = {db.get(Grant, r["grant_id"]).beneficiary_id for r in payout.recipients}
            if user.id in beneficiaries:
                raise HTTPException(403, "You can't sign a payout that pays you.")
            from clans.access_service import recovery_hold

            if recovery_hold(db, user.id):
                raise HTTPException(
                    409, "An account recovery is waiting. Block it or finish it before signing."
                )
            try:
                accept_signature(db, payout, data.psbt, {key.fingerprint: ("signer", user.id)})
            except ClanWalletError as exc:
                raise HTTPException(409, str(exc)) from exc
            audit(
                db,
                clan_id,
                user.id,
                "payout_signed",
                payout_id=payout.id,
                txid=payout.txid,
                fingerprint=key.fingerprint,
            )
            return payout_view(db, payout, policy, user.id)

    @app.post("/api/clans/{clan_id}/wallet/payouts/{payout_id}/oversight-signature")
    def oversight_sign(
        clan_id: str, payout_id: str, data: OversightSignatureInput, request: Request
    ):
        """For the Afribit oversight tool, which has no Clans session.

        The signature authenticates itself: only an oversight key's signature on this exact
        payment is accepted, and the chain watcher verifies it before broadcasting.
        """
        require_enabled()
        security.limit(request, "oversight-signature", 30, 3600)
        if not request.headers.get("content-type", "").startswith("application/json"):
            raise HTTPException(415, "JSON is required.")
        with security.db() as db:
            lock_clan(db, clan_id)
            payout = visible_payout(db, clan_id, payout_id)
            record, policy = paying_wallet(db, payout)
            signable(db, payout)
            if (data.id or payout_id, data.clan_id or clan_id, data.txid or payout.txid) != (
                payout_id,
                clan_id,
                payout.txid,
            ):
                raise HTTPException(409, "This signed file is for a different payout.")
            allowed = {
                SignerKey.parse(key).fingerprint: ("oversight", None)
                for key in record.oversight_keys
            }
            try:
                row = accept_signature(db, payout, data.psbt, allowed)
            except ClanWalletError as exc:
                raise HTTPException(409, str(exc)) from exc
            audit(
                db,
                clan_id,
                actor(db, clan_id),
                "payout_oversight_signed",
                source="afribit_oversight",
                payout_id=payout.id,
                txid=payout.txid,
                fingerprint=row.fingerprint,
            )
            signed = signatures(db, payout)
            return {
                "id": payout.id,
                "txid": payout.txid,
                "oversight_signed": signed.oversight,
                "signatures": {"count": len(signed.signers), "required": policy.threshold},
            }

    def oversight_reader(request: Request, db) -> communities.Oversight:
        """A laptop's read token: which community it oversees. It lists that community's
        payouts; approving still needs the oversight key."""
        if not communities.any_readers(db, settings):
            raise HTTPException(503, "Oversight downloads aren't set up.")
        security.limit(request, "oversight-read", 120, 3600)
        header = request.headers.get("authorization", "")
        token = header[7:].strip() if header[:7].lower() == "bearer " else ""
        found = communities.reader(db, settings, token)
        if found is None:
            raise HTTPException(401, "This oversight token isn't valid.")
        return found

    @app.get("/api/oversight/community")
    def oversight_community(request: Request):
        """The community this laptop oversees, so the app can say whose payouts it shows."""
        require_enabled()
        with security.db() as db:
            found = oversight_reader(request, db)
            return {"name": found.name, "oversight_keys": len(found.keys)}

    @app.get("/api/oversight/report")
    def oversight_report(
        request: Request,
        start: str = Query(alias="from", pattern=r"^\d{4}-\d{2}-\d{2}$"),
        end: str = Query(alias="to", pattern=r"^\d{4}-\d{2}-\d{2}$"),
        format: str = Query(default="json", pattern="^(json|csv)$"),
    ):
        """This community's clans for a period: members, usage, grants and repayments."""
        require_enabled()
        with security.db() as db:
            found = oversight_reader(request, db)
            try:
                data = reports.report(db, communities.in_community(found.community_id), start, end)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
        data["community"] = found.name
        if format == "csv":
            return Response(reports.as_csv(data), media_type="text/csv")
        return data

    @app.get("/api/clans/{clan_id}/wallet/alarms")
    def clan_alarms(clan_id: str, request: Request):
        """Alarms about this clan's wallets that members should know about, newest first."""
        with security.db() as db:
            user = security.current(request, db)
            membership(db, clan_id, user.id)
            return alarm_views(db, clan_id=clan_id, members_only=True, limit=50)

    @app.get("/api/oversight/alarms")
    def oversight_alarms(request: Request, since: str | None = None):
        """Alarms about this laptop's community's clans, newest first, optionally after `since`."""
        require_enabled()
        if since is not None:
            try:
                parsed = datetime.fromisoformat(since)
            except ValueError as exc:
                raise HTTPException(422, "since must be a date and time.") from exc
            # A time without a zone is taken as UTC, like every time Clans stores.
            parsed = parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
            since = parsed.astimezone(UTC).isoformat()
        with security.db() as db:
            clans = communities.in_community(oversight_reader(request, db).community_id)
            return with_clan_names(db, alarm_views(db, clan_ids=clans, since=since, limit=200))

    @app.get("/api/oversight/wallets")
    def oversight_wallets(request: Request):
        """The community's active clan wallets, to register after a phone check of the code."""
        require_enabled()
        with security.db() as db:
            clans = communities.in_community(oversight_reader(request, db).community_id)
            records = db.scalars(
                select(ClanWalletRecord)
                .where(ClanWalletRecord.status == "active", ClanWalletRecord.clan_id.in_(clans))
                .order_by(ClanWalletRecord.clan_id, ClanWalletRecord.generation)
            ).all()
            views = [
                {
                    "clan_id": record.clan_id,
                    "generation": record.generation,
                    # The laptop trusts this only once a signatory's phone gives the same code.
                    "policy": policy_view(record, wallet_keys(db, record).values()),
                }
                for record in records
            ]
            return with_clan_names(db, views)

    @app.get("/api/oversight/payouts")
    def oversight_payouts(request: Request):
        """Payouts the clan has signed that wait for an Afribit approval, oldest first."""
        require_enabled()
        with security.db() as db:
            clans = communities.in_community(oversight_reader(request, db).community_id)
            views = []
            for payout in db.scalars(
                select(WalletPayout)
                .join(ClanWalletRecord, ClanWalletRecord.id == WalletPayout.wallet_id)
                .where(
                    WalletPayout.status == "awaiting_signatures",
                    ClanWalletRecord.clan_id.in_(clans),
                )
                .order_by(WalletPayout.created_at)
                .limit(200)
            ):
                record = db.get(ClanWalletRecord, payout.wallet_id)
                if record.activated_at is None or record.status not in {"active", "retired"}:
                    continue
                try:
                    policy = record_policy(db, record)
                except ClanWalletError:
                    continue  # never shown for approval; the chain watcher reports it failing
                view = payout_view(db, payout, policy, None)
                if view["status"] == "awaiting_oversight":
                    views.append(view)
            return with_clan_names(db, views)
