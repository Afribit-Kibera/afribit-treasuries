"""BTCPay Greenfield and its dedicated LND: exact amounts and independently checked proofs."""

import hashlib
import time
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import quote, urlparse

import bolt11
import httpx


class ProviderError(Exception):
    """An external result is unavailable or inconsistent. Never log credential-bearing responses."""


class PayoutDeferred(ProviderError):
    """An expected payment-local refusal; no integrity check may use this class."""

    def __init__(self, message, reason, retry_seconds=300):
        super().__init__(message)
        self.reason = reason
        self.retry_seconds = retry_seconds


class ProviderUnavailable(ProviderError):
    """Transport/temporary HTTP failure, never an invalid payment proof."""


def integer(value, *, scale=1) -> int:
    try:
        number = Decimal(str(value)) * scale
        if not number.is_finite() or number != number.to_integral_value() or number < 0:
            raise ValueError
        return int(number)
    except (ValueError, InvalidOperation, TypeError) as exc:
        raise ProviderError("Invalid provider amount") from exc


def decode_invoice(value: str, *, allow_expired=False) -> dict:
    value = value.strip()
    if value.lower().startswith("lightning:"):
        value = value[10:]
    if len(value) > 12_000 or not value.lower().startswith("lnbc"):
        raise ProviderError("A Bitcoin mainnet Lightning invoice is required")
    try:
        invoice = bolt11.decode(value.lower())
        if invoice.currency != "bc" or not invoice.amount_msat or not invoice.payee:
            raise ValueError
        if not allow_expired and invoice.expiry_time <= time.time() + 60:
            raise ProviderError("The invoice expires too soon; create one with a longer expiry")
        return {
            "bolt11": value.lower(),
            "payment_hash": invoice.payment_hash.lower(),
            "amount_msat": int(invoice.amount_msat),
            "payee": invoice.payee.lower(),
            "expires_at": datetime.fromtimestamp(invoice.expiry_time, UTC).isoformat(),
            "route_hint_count": len(invoice.route_hints),
        }
    except ProviderError:
        raise
    except Exception as exc:
        raise ProviderError("The Lightning invoice signature or fields are invalid") from exc


def verify_preimage(preimage: str, payment_hash: str):
    try:
        raw = bytes.fromhex(preimage)
        if len(raw) != 32 or hashlib.sha256(raw).hexdigest() != payment_hash:
            raise ValueError
    except (ValueError, TypeError) as exc:
        raise ProviderError("Invalid settlement proof") from exc


class TreasuryProvider:
    def __init__(self, settings, *, transport=None):
        self.settings = settings
        self._probe_hash = None
        self.prefix = "/api/v1/stores/" + quote(settings.btcpay_store_id, safe="")
        self.client = httpx.Client(
            base_url=settings.btcpay_url,
            timeout=httpx.Timeout(45, connect=10),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
            headers={"Authorization": "token " + settings.btcpay_api_key.get_secret_value()},
        )

    def close(self):
        self.client.close()

    def kes_rate(self):
        """New, timestamped quote for a new dispatch; no stale-rate fallback."""
        from clans.fiat_limits import fetch_kes_quote

        return fetch_kes_quote()

    def request(self, method, path, *, body=None, params=None, missing=False):
        try:
            response = self.client.request(method, self.prefix + path, json=body, params=params)
            if response.status_code == 404 and missing:
                return None
            if response.status_code == 429 or response.status_code >= 500:
                raise ProviderUnavailable("Provider temporarily unavailable")
            if response.status_code not in {200, 201, 202}:
                raise ProviderError("Provider request needs reconciliation")
            return response.json()
        except httpx.HTTPError as exc:
            raise ProviderUnavailable("Provider connection needs reconciliation") from exc
        except ValueError as exc:
            raise ProviderError("Provider connection needs reconciliation") from exc

    def verify_node(self):
        info = self.request("GET", "/lightning/BTC/info")
        identities = [str(uri).split("@", 1)[0] for uri in info.get("nodeURIs", [])]
        # The certificate-pinned store connection is also tested by the provisioning step.
        if identities and self.settings.expected_node_pubkey not in identities:
            raise ProviderError("Dedicated treasury node identity mismatch")
        if not identities:
            # This private node advertises no public URI. Verify a signed invoice from
            # the certificate-pinned node API instead of requiring public peering.
            missing_hash = None
            if self._probe_hash:
                proof = self.request(
                    "GET", "/lightning/BTC/invoices/" + self._probe_hash, missing=True
                )
                if proof is None:
                    missing_hash = self._probe_hash
                    self._probe_hash = None
                else:
                    decoded = decode_invoice(proof.get("BOLT11", ""), allow_expired=True)
                    if (
                        decoded["payee"] != self.settings.expected_node_pubkey
                        or decoded["payment_hash"] != self._probe_hash
                    ):
                        raise ProviderError("Dedicated treasury node identity mismatch")
            if not self._probe_hash:
                rows = self.request("GET", "/lightning/BTC/invoices", params={"pendingOnly": False})
                for row in reversed(rows[-32:]):
                    decoded = decode_invoice(row.get("BOLT11", ""), allow_expired=True)
                    if (
                        decoded["payee"] != self.settings.expected_node_pubkey
                        or decoded["payment_hash"] == missing_hash
                    ):
                        continue
                    # The list can outlive the individual lookup for an old invoice.
                    # A listed BOLT11 alone is not sufficient node-connection proof.
                    proof = self.request(
                        "GET", "/lightning/BTC/invoices/" + decoded["payment_hash"], missing=True
                    )
                    if proof is None:
                        continue
                    verified = decode_invoice(proof.get("BOLT11", ""), allow_expired=True)
                    if (
                        verified["payee"] != self.settings.expected_node_pubkey
                        or verified["payment_hash"] != decoded["payment_hash"]
                    ):
                        raise ProviderError("Dedicated treasury node identity mismatch")
                    self._probe_hash = decoded["payment_hash"]
                    break
            if not self._probe_hash:
                raise ProviderError("Cannot verify the private treasury node identity")
        if info.get("blockHeight", 0) <= 0:
            raise ProviderError("Treasury node is not synchronized")
        return info

    def order_id(self, incoming_id):
        return self.settings.provider_namespace + ":" + incoming_id

    def find_invoice(self, incoming_id):
        order = self.order_id(incoming_id)
        rows = self.request("GET", "/invoices", params={"orderId": order, "take": 100})
        matches = [row for row in rows if row.get("metadata", {}).get("orderId") == order]
        if len(matches) > 1:
            raise ProviderError("Duplicate provider invoices require operator reconciliation")
        return matches[0] if matches else None

    def create_invoice(
        self,
        incoming_id,
        amount_sats,
        *,
        description="AfriBit Clans",
        clan_id=None,
        receive_authorization=None,
    ):
        return self.request(
            "POST",
            "/invoices",
            body={
                "amount": str(amount_sats),
                "currency": "SATS",
                "metadata": {
                    "orderId": self.order_id(incoming_id),
                    "clansRequestId": incoming_id,
                    "itemDesc": description[:160],
                    "clansReceiveAuthorization": receive_authorization,
                },
                "checkout": {
                    "expirationMinutes": 60,
                    "redirectURL": self.settings.public_origin
                    + "/?payment="
                    + quote(incoming_id, safe="")
                    + ("&clan=" + quote(clan_id, safe="") if clan_id else ""),
                    "redirectAutomatically": True,
                    "paymentMethods": ["BTC-LN"],
                    "lightningPrivateRouteHints": True,
                },
            },
        )

    def invoice(self, invoice_id):
        return self.request("GET", "/invoices/" + quote(invoice_id, safe=""))

    def payment_methods(self, invoice_id):
        return self.request("GET", "/invoices/" + quote(invoice_id, safe="") + "/payment-methods")

    def receive_details(self, invoice, incoming_id, amount_sats):
        if invoice.get("currency") != "SATS" or integer(invoice.get("amount")) != amount_sats:
            raise ProviderError("Provider invoice amount mismatch")
        if invoice.get("metadata", {}).get("orderId") != self.order_id(incoming_id):
            raise ProviderError("Provider invoice ownership mismatch")
        methods = [
            m for m in self.payment_methods(invoice["id"]) if m.get("paymentMethodId") == "BTC-LN"
        ]
        if len(methods) != 1:
            raise ProviderError("Expected one Lightning payment method")
        decoded = decode_invoice(methods[0]["destination"], allow_expired=True)
        if (
            decoded["amount_msat"] != amount_sats * 1000
            or decoded["payee"] != self.settings.expected_node_pubkey
        ):
            raise ProviderError("Receive invoice does not belong to the dedicated treasury")
        if not decoded["route_hint_count"]:
            raise ProviderError("Private treasury channels require invoice route hints")
        checkout = invoice.get("checkoutLink", "")
        if (
            urlparse(checkout).scheme != "https"
            or urlparse(checkout).netloc != urlparse(self.settings.btcpay_url).netloc
        ):
            raise ProviderError("Unexpected checkout origin")
        return {
            **decoded,
            "checkout_url": checkout,
            "provider_invoice_id": invoice["id"],
            "methods": methods,
        }

    def settlement(self, invoice, incoming_id, amount_sats):
        details = self.receive_details(invoice, incoming_id, amount_sats)
        payments = [
            p
            for m in details["methods"]
            for p in m.get("payments", [])
            if p.get("status") == "Settled"
        ]
        if not payments:
            return None
        if len(payments) != 1 or str(payments[0].get("id", "")).lower() != details["payment_hash"]:
            raise ProviderError("Settlement reference mismatch")
        amount = integer(payments[0].get("value"), scale=100_000_000_000)
        node = self.request("GET", "/lightning/BTC/invoices/" + details["payment_hash"])
        if (
            node.get("status") != "Paid"
            or str(node.get("paymentHash", "")).lower() != details["payment_hash"]
        ):
            raise ProviderError("Node has not confirmed the incoming settlement")
        if integer(node.get("amountReceived")) != amount or amount <= 0:
            raise ProviderError("Node and provider settlement amounts differ")
        verify_preimage(node.get("preimage"), details["payment_hash"])
        return {"payment_hash": details["payment_hash"], "amount_msat": amount}

    def payment(self, payment_hash):
        return self.request("GET", "/lightning/BTC/payments/" + payment_hash, missing=True)

    def send(self, invoice, fee_limit_sats):
        # LND atomically keys attempts by the invoice hash. Always reconcile via payment().
        return self.request(
            "POST",
            "/lightning/BTC/invoices/pay",
            body={
                "BOLT11": invoice,
                "maxFeeFlat": str(fee_limit_sats),
                "sendTimeout": 30,
            },
        )

    def payout_proof(self, data, payment_hash, amount_msat):
        if data.get("status") != "Complete":
            raise ProviderError("Payment is not complete")
        if str(data.get("paymentHash", "")).lower() != payment_hash:
            raise ProviderError("Payout payment hash mismatch")
        verify_preimage(data.get("preimage"), payment_hash)
        fee = integer(data.get("feeAmount"))
        if integer(data.get("totalAmount")) != amount_msat + fee:
            raise ProviderError("Payout amount mismatch")
        if (
            data.get("BOLT11")
            and decode_invoice(data["BOLT11"], allow_expired=True)["payment_hash"] != payment_hash
        ):
            raise ProviderError("Payout invoice mismatch")
        return fee
