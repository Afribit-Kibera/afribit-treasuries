"""Worker-only authorization, independent from web/session secrets and mutable status strings.

This is not an independent identity trust root. A privileged writer replacing the
signer registry before initial authorization remains outside this control's scope.
"""

import hashlib
import hmac
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text

from clans.fiat_limits import KesQuote, kes_minor
from clans.models import now_iso
from clans.money_models import DispatchAuthorization
from clans.money_service import canonical_json, intent_digest
from clans.treasury_provider import PayoutDeferred, ProviderError


def validate_worker_settings(settings):
    secret = settings.dispatch_secret.get_secret_value()
    if (
        len(secret) < 48
        or secret == settings.session_secret.get_secret_value()
        or secret == settings.btcpay_api_key.get_secret_value()
    ):
        raise ValueError("Treasury requires an independent worker-only dispatch secret")
    if settings.payout_budget_currency == "KES":
        if not all(
            [settings.payout_global_24h_kes, settings.payout_clan_24h_kes, settings.max_payout_kes]
        ):
            raise ValueError("Treasury requires explicit positive KES limits")
        if (
            settings.payout_clan_24h_kes > settings.payout_global_24h_kes
            or settings.max_payout_kes > settings.payout_clan_24h_kes
        ):
            raise ValueError("KES payout and clan limits must fit the global budget")
    elif not settings.payout_global_24h_sats or not settings.payout_clan_24h_sats:
        raise ValueError("Treasury requires explicit positive 24-hour spending budgets")
    if settings.payout_clan_24h_sats > settings.payout_global_24h_sats:
        raise ValueError("The clan budget cannot exceed the global budget")
    from clans.signer_trust import validate_trust_settings

    validate_trust_settings(settings)


def tag(settings, record):
    body = {
        "domain": "afribit-dispatch-v1",
        "namespace": settings.provider_namespace,
        "provider_origin": settings.btcpay_url.rstrip("/"),
        "store": settings.btcpay_store_id,
        "node": settings.expected_node_pubkey,
        "payout_id": record.payout_id,
        "clan_id": record.clan_id,
        "intent_digest": record.intent_digest,
        "payment_hash": record.payment_hash,
        "amount_msat": record.amount_msat,
        "fee_limit_msat": record.fee_limit_msat,
        "authorized_at": record.authorized_at,
    }
    if (
        record.kes_per_btc is not None
        or record.kes_cost_minor is not None
        or record.kes_rate_published_at is not None
        or record.signer_trust_digest is not None
    ):
        body.update(
            domain="afribit-dispatch-v2",
            kes_per_btc=record.kes_per_btc,
            kes_cost_minor=record.kes_cost_minor,
            kes_rate_published_at=record.kes_rate_published_at,
            signer_trust_digest=record.signer_trust_digest,
        )
    return hmac.new(
        settings.dispatch_secret.get_secret_value().encode(),
        canonical_json(body).encode(),
        hashlib.sha256,
    ).hexdigest()


def verify_record(settings, record):
    if not hmac.compare_digest(record.authentication_tag, tag(settings, record)):
        raise ProviderError("Dispatch authorization failed authentication")


def verify_binding(settings, record, payout, intent, grant):
    verify_record(settings, record)
    if (
        record.payout_id != payout.id
        or record.clan_id != grant.clan_id
        or record.intent_digest != intent.digest
        or intent.digest != intent_digest(intent.canonical)
        or intent.canonical["clan_id"] != grant.clan_id
        or intent.canonical["grant_id"] != grant.id
        or intent.canonical["beneficiary_id"] != grant.beneficiary_id
        or grant.amount_sats * 1000 != record.amount_msat
        or intent.canonical["amount_msat"] != record.amount_msat
        or intent.canonical["fee_limit_msat"] != record.fee_limit_msat
        or intent.canonical["payment_hash"] != record.payment_hash
        or intent.canonical["bolt11_sha256"] != hashlib.sha256(intent.bolt11.encode()).hexdigest()
        or payout.payment_hash != record.payment_hash
        or intent.payment_hash != record.payment_hash
        or payout.amount_msat != record.amount_msat
        or payout.fee_limit_msat != record.fee_limit_msat
    ):
        raise ProviderError("Dispatched payment changed; operator reconciliation required")


def authorize(db, settings, payout, intent, grant, kes_per_btc=None, signer_trust_digest=None):
    """Called only after full checks, in the transaction committed BEFORE external I/O.

    Every authorization consumes principal + maximum fee for 24h, even on failure.
    Never refund budget on a timeout, state change or newly reported failure.
    """
    if db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(24110302)"))
    cutoff = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
    fiat = settings.payout_budget_currency == "KES"
    if fiat:
        if not isinstance(kes_per_btc, KesQuote):
            raise ProviderError("A timestamped BTC/KES quote is required")
        kes_per_btc.validate()
    rate = kes_per_btc.rate if fiat else None
    global_total, clan_total = 0, 0
    for record in db.scalars(
        select(DispatchAuthorization).where(DispatchAuthorization.authorized_at > cutoff)
    ).all():
        verify_record(settings, record)
        cost = record.amount_msat + record.fee_limit_msat
        if fiat:
            # Legacy sat-only authorizations still consume budget at the current
            # rate. New KES authorizations always retain their original valuation.
            cost = (
                record.kes_cost_minor
                if record.kes_cost_minor is not None
                else kes_minor(cost, rate)
            )
        global_total += cost
        if record.clan_id == grant.clan_id:
            clan_total += cost
    cost = payout.amount_msat + payout.fee_limit_msat
    if fiat:
        if kes_minor(cost, rate) > settings.max_payout_kes * 100:
            raise PayoutDeferred("The payout exceeds the KES limit", "payment_limit_reached", 60)
        cost = kes_minor(cost, rate)
    global_cap = (
        settings.payout_global_24h_kes * 100 if fiat else settings.payout_global_24h_sats * 1000
    )
    clan_cap = settings.payout_clan_24h_kes * 100 if fiat else settings.payout_clan_24h_sats * 1000
    if global_total + cost > global_cap or clan_total + cost > clan_cap:
        raise PayoutDeferred("Rolling treasury spending budget exhausted", "daily_payment_limit")
    record = DispatchAuthorization(
        payout_id=payout.id,
        clan_id=grant.clan_id,
        intent_digest=intent.digest,
        payment_hash=payout.payment_hash,
        amount_msat=payout.amount_msat,
        fee_limit_msat=payout.fee_limit_msat,
        authorized_at=now_iso(),
        kes_per_btc=str(rate) if fiat else None,
        kes_cost_minor=cost if fiat else None,
        kes_rate_published_at=kes_per_btc.published_at if fiat else None,
        signer_trust_digest=signer_trust_digest,
    )
    record.authentication_tag = tag(settings, record)
    db.add(record)
    db.flush()
    return record
