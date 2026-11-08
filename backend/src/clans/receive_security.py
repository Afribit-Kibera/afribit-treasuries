"""Receiving attribution is independent of web-writable account/governance rows."""

import hashlib
import hmac
import json

from clans.money_models import ReceiveAuthorization, ReceiveInvoiceBinding
from clans.treasury_provider import ProviderError


class ReceiveBindingError(ProviderError):
    pass


def validate_receive_settings(settings):
    secret = settings.dispatch_secret.get_secret_value()
    if len(secret) < 48 or secret in {
        settings.session_secret.get_secret_value(),
        settings.btcpay_api_key.get_secret_value(),
    }:
        raise ValueError("Receiving requires an independent worker-only secret")


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def tag(settings, domain, value):
    return hmac.new(
        settings.dispatch_secret.get_secret_value().encode(),
        (domain + ":" + digest(value)).encode(),
        hashlib.sha256,
    ).hexdigest()


def identity(settings, row):
    return {
        "request_id": row.id,
        "clan_id": row.clan_id,
        "user_id": row.user_id,
        "grant_id": row.grant_id,
        "amount_sats": row.amount_sats,
        "method": row.method,
        "namespace": settings.provider_namespace,
        "store": settings.btcpay_store_id,
        "provider": settings.btcpay_url.rstrip("/"),
        "node": settings.expected_node_pubkey,
    }


def accept(settings, row):
    value = identity(settings, row)
    return ReceiveAuthorization(
        incoming_id=row.id, identity=value, authentication_tag=tag(settings, "receive-v1", value)
    )


def verify(settings, row, authorization):
    if (
        not authorization
        or authorization.identity != identity(settings, row)
        or not hmac.compare_digest(
            authorization.authentication_tag, tag(settings, "receive-v1", authorization.identity)
        )
    ):
        raise ReceiveBindingError("Receiving allocation changed or lacks authorization")


def invoice_value(authorization, invoice_id, payment_hash, bolt_digest):
    return {
        "authorization": authorization.authentication_tag,
        "invoice": invoice_id,
        "hash": payment_hash,
        "bolt11": bolt_digest,
    }


def bind(settings, authorization, details):
    bolt_digest = hashlib.sha256(details["bolt11"].encode()).hexdigest()
    value = invoice_value(
        authorization, details["provider_invoice_id"], details["payment_hash"], bolt_digest
    )
    return ReceiveInvoiceBinding(
        incoming_id=authorization.incoming_id,
        provider_invoice_id=details["provider_invoice_id"],
        payment_hash=details["payment_hash"],
        bolt11_digest=bolt_digest,
        authentication_tag=tag(settings, "receive-invoice-v1", value),
    )


def verify_invoice(settings, row, authorization, binding, details=None, proof=None):
    verify(settings, row, authorization)
    value = invoice_value(
        authorization, binding.provider_invoice_id, binding.payment_hash, binding.bolt11_digest
    )
    if not hmac.compare_digest(
        binding.authentication_tag, tag(settings, "receive-invoice-v1", value)
    ):
        raise ReceiveBindingError("Receiving invoice binding changed")
    if row.provider_invoice_id not in {None, binding.provider_invoice_id} or (
        row.bolt11 and hashlib.sha256(row.bolt11.encode()).hexdigest() != binding.bolt11_digest
    ):
        raise ReceiveBindingError("Receiving invoice was relabelled")
    if details and (
        details["provider_invoice_id"] != binding.provider_invoice_id
        or details["payment_hash"] != binding.payment_hash
        or hashlib.sha256(details["bolt11"].encode()).hexdigest() != binding.bolt11_digest
    ):
        raise ReceiveBindingError("Provider returned a different receiving invoice")
    if proof and proof["payment_hash"] != binding.payment_hash:
        raise ReceiveBindingError("Settlement belongs to another receiving invoice")
