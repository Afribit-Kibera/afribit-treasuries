"""Private-node proof selection survives pruned invoices without trusting a list alone."""

import secrets

import httpx
import pytest
from coincurve import PrivateKey
from test_money import invoice

from clans.live_config import LiveSettings
from clans.treasury_provider import ProviderError, TreasuryProvider, decode_invoice


def fixture():
    key = secrets.token_hex(32)
    pubkey = PrivateKey(bytes.fromhex(key)).public_key.format().hex()
    bolts = [invoice(1000, key)[0] for _ in range(3)]
    hashes = [decode_invoice(bolt)["payment_hash"] for bolt in bolts]
    return pubkey, bolts, hashes


def provider(pubkey, handler):
    return TreasuryProvider(
        LiveSettings(
            database_url="sqlite://",
            environment="test",
            session_secret="a" * 64,
            expected_node_pubkey=pubkey,
            btcpay_store_id="unit-store",
        ),
        transport=httpx.MockTransport(handler),
    )


def test_missing_newest_probe_falls_back_and_refreshes_a_pruned_cached_probe():
    pubkey, bolts, hashes = fixture()
    missing = {hashes[2]}
    requested = []

    def handle(request):
        assert request.method == "GET"
        path = request.url.path
        if path.endswith("/info"):
            return httpx.Response(200, json={"nodeURIs": [], "blockHeight": 900000})
        if path.endswith("/invoices"):
            return httpx.Response(200, json=[{"BOLT11": bolt} for bolt in bolts])
        payment_hash = path.rsplit("/", 1)[1]
        requested.append(payment_hash)
        if payment_hash in missing:
            return httpx.Response(404, json={"code": "not-found"})
        return httpx.Response(200, json={"BOLT11": bolts[hashes.index(payment_hash)]})

    p = provider(pubkey, handle)
    try:
        assert p.verify_node()["blockHeight"] > 0
        assert p._probe_hash == hashes[1]
        missing.add(hashes[1])
        assert p.verify_node()["blockHeight"] > 0
        assert p._probe_hash == hashes[0]
        assert hashes[2] in requested and hashes[0] in requested
    finally:
        p.close()


@pytest.mark.parametrize("failure", ["all_missing", "wrong_node", "wrong_invoice", "forbidden"])
def test_listed_invoice_is_not_sufficient_proof(failure):
    pubkey, bolts, hashes = fixture()
    other = invoice(1000)[0] if failure == "wrong_node" else bolts[0]

    def handle(request):
        assert request.method == "GET"
        path = request.url.path
        if path.endswith("/info"):
            return httpx.Response(200, json={"nodeURIs": [], "blockHeight": 900000})
        if path.endswith("/invoices"):
            return httpx.Response(200, json=[{"BOLT11": bolts[2]}])
        if failure in {"all_missing", "forbidden"}:
            return httpx.Response(404 if failure == "all_missing" else 403, json={})
        return httpx.Response(200, json={"BOLT11": other})

    p = provider(pubkey, handle)
    try:
        with pytest.raises(ProviderError):
            p.verify_node()
        assert p._probe_hash is None
    finally:
        p.close()
