"""External-network fixtures only: real invoices, signatures, accounting and worker state."""

import hashlib
import json
import secrets
import time
from decimal import Decimal

import bolt11
import httpx
import pytest
from bolt11.models.routehint import Route, RouteHint
from coincurve import PrivateKey
from pydantic import SecretStr
from sqlalchemy import func, select
from test_live_app import clan, join, signup
from test_live_app import live as live

from clans.live_app import create_app
from clans.live_models import Grant, Passkey, PaymentIntent, SignerApproval
from clans.models import new_id
from clans.money_models import Balance, Debt, DepositReceipt, LedgerEntry, Payout, WorkerStatus
from clans.treasury_provider import ProviderError, TreasuryProvider, decode_invoice
from clans.treasury_worker import TreasuryWorker


def invoice(amount_msat, private_key=None, *, hints=False):
    key = private_key or secrets.token_hex(32)
    preimage = secrets.token_hex(32)
    payment_hash = hashlib.sha256(bytes.fromhex(preimage)).hexdigest()
    tags = [
        bolt11.Tag(bolt11.TagChar.payment_hash, payment_hash),
        bolt11.Tag(bolt11.TagChar.payment_secret, secrets.token_hex(32)),
        bolt11.Tag(bolt11.TagChar.description, "Private unit-test invoice"),
        bolt11.Tag(bolt11.TagChar.expire_time, 3600),
    ]
    if hints:
        tags.append(
            bolt11.Tag(
                bolt11.TagChar.route_hint,
                RouteHint(
                    [
                        Route(
                            PrivateKey(bytes.fromhex(key)).public_key.format().hex(),
                            "1x0x0",
                            1,
                            1,
                            40,
                        )
                    ]
                ),
            )
        )
    encoded = bolt11.encode(
        bolt11.Bolt11(
            currency="bc",
            date=int(time.time()),
            amount_msat=bolt11.MilliSatoshi(amount_msat),
            tags=bolt11.Tags(tags),
        ),
        private_key=key,
    )
    return encoded, preimage


class NetworkFixture:
    def __init__(self):
        self.key = secrets.token_hex(32)
        self.pubkey = PrivateKey(bytes.fromhex(self.key)).public_key.format().hex()
        self.invoices = {}
        self.outgoing = {}
        self.payee_preimages = {}
        self.create_calls = 0
        self.pay_calls = 0
        self.paid = False
        self.bad_proof = False
        self.timeout_create = False
        self.timeout_send = False
        self.pending_send = False
        self.node_uris = True

    def handle(self, request):
        path = request.url.path
        body = json.loads(request.content) if request.content else None
        status, data = 200, None
        if path.endswith("/lightning/BTC/info"):
            data = {
                "nodeURIs": [self.pubkey + "@localhost:9735"] if self.node_uris else [],
                "blockHeight": 900000,
            }
        elif path.endswith("/invoices") and "/lightning/" not in path and request.method == "POST":
            self.create_calls += 1
            encoded, preimage = invoice(int(body["amount"]) * 1000, self.key, hints=True)
            decoded = decode_invoice(encoded)
            data = {
                "id": secrets.token_hex(8),
                "currency": "SATS",
                "amount": body["amount"],
                "metadata": body["metadata"],
                "checkoutLink": "https://pay.insats.org/i/unit",
                "status": "New",
                "bolt": encoded,
                "preimage": preimage,
                "payment_hash": decoded["payment_hash"],
            }
            self.invoices[data["id"]] = data
            if self.timeout_create:
                self.timeout_create = False
                raise httpx.ReadTimeout("Unit transport lost the creation response")
        elif path.endswith("/invoices") and "/lightning/" not in path:
            order = request.url.params.get("orderId")
            data = [row for row in self.invoices.values() if row["metadata"]["orderId"] == order]
        elif path.endswith("/payment-methods"):
            row = self.invoices[path.split("/")[-2]]
            payments = (
                [
                    {
                        "status": "Settled",
                        "id": row["payment_hash"],
                        "value": str(Decimal(row["amount"]) / 100_000_000),
                    }
                ]
                if self.paid
                else []
            )
            data = [{"paymentMethodId": "BTC-LN", "destination": row["bolt"], "payments": payments}]
        elif "/lightning/BTC/invoices/" in path and not path.endswith("/pay"):
            payment_hash = path.split("/")[-1]
            row = next(row for row in self.invoices.values() if row["payment_hash"] == payment_hash)
            data = self.node_invoice(row)
        elif path.endswith("/lightning/BTC/invoices"):
            data = [self.node_invoice(row) for row in self.invoices.values()]
        elif path.endswith("/lightning/BTC/invoices/pay"):
            self.pay_calls += 1
            decoded = decode_invoice(body["BOLT11"])
            assert body["maxFeeFlat"] == "1"
            payment_hash = decoded["payment_hash"]
            data = {
                "status": "Pending" if self.pending_send else "Complete",
                "paymentHash": payment_hash,
                "BOLT11": body["BOLT11"],
                "preimage": self.payee_preimages[payment_hash],
                "totalAmount": str(decoded["amount_msat"] + 123),
                "feeAmount": "123",
            }
            self.outgoing[payment_hash] = data
            if self.timeout_send:
                self.timeout_send = False
                raise httpx.ReadTimeout("Unit transport lost a successful payment response")
        elif "/lightning/BTC/payments/" in path:
            data = self.outgoing.get(path.split("/")[-1])
            if data is None:
                status, data = 404, {"code": "payment-not-found"}
        elif "/invoices/" in path:
            data = self.invoices[path.split("/")[-1]]
        else:
            raise AssertionError("Unexpected fixture request: " + path)
        return httpx.Response(status, json=data)

    def node_invoice(self, row):
        return {
            "status": "Paid" if self.paid else "Unpaid",
            "paymentHash": row["payment_hash"],
            "BOLT11": row["bolt"],
            "preimage": "0" * 64 if self.bad_proof else row["preimage"],
            "amount": str(int(row["amount"]) * 1000),
            "amountReceived": str(int(row["amount"]) * 1000) if self.paid else "0",
        }


@pytest.fixture
def money(live):
    network = NetworkFixture()
    settings = live.state.security.settings.model_copy(
        update={
            "receiving_enabled": True,
            "payouts_enabled": True,
            "btcpay_store_id": "unit-store",
            "btcpay_api_key": SecretStr("unit-key"),
            "expected_node_pubkey": network.pubkey,
            "provider_namespace": "unit-test",
            "dispatch_secret": SecretStr(secrets.token_urlsafe(64)),
            "payout_global_24h_sats": 10_000,
            "payout_clan_24h_sats": 5_000,
        }
    )
    app = create_app(settings)
    worker = TreasuryWorker(
        settings, provider=TreasuryProvider(settings, transport=httpx.MockTransport(network.handle))
    )
    worker.status("ready")
    yield app, worker, network
    worker.provider.close()
    worker.security.engine.dispose()
    app.state.security.engine.dispose()


def funded(money):
    app, worker, network = money
    owner, auth, _, _ = signup(app, "Owner")
    cid = clan(owner)
    response = owner.post(
        f"/api/clans/{cid}/deposits",
        json={"amount_sats": 1000},
        headers={"Idempotency-Key": secrets.token_hex(16)},
    )
    assert response.status_code == 200, response.text
    request_id = response.json()["request_id"]
    worker.tick()
    assert owner.get(f"/api/clans/{cid}").json()["balance_msat"] == "0"
    network.paid = True
    worker.tick()
    assert owner.get(f"/api/clans/{cid}").json()["balance_msat"] == "1000000"
    return owner, auth, cid, request_id


def prepared(money):
    app, worker, network = money
    owner, owner_key, cid, _ = funded(money)
    a, key_a, _, _ = signup(app, "Signer A")
    b, key_b, _, _ = signup(app, "Signer B")
    join(owner, a, cid)
    join(owner, b, cid)
    response = owner.post(
        f"/api/clans/{cid}/grants",
        json={"purpose": "Inventory for a business", "amount_sats": 100},
        headers={"Idempotency-Key": secrets.token_hex(16)},
    )
    assert response.status_code == 200, response.text
    gid = response.json()["grant_id"]
    prefix = f"/api/clans/{cid}/grants/{gid}"
    for voter in [a, b]:
        assert voter.post(prefix + "/vote", json={"choice": "approve"}).status_code == 200
    assert owner.post(prefix + "/accept", json={}).status_code == 200
    bolt, preimage = invoice(100_000)
    payment_hash = decode_invoice(bolt)["payment_hash"]
    network.payee_preimages[payment_hash] = preimage
    response = owner.post(
        prefix + "/destination",
        json={"bolt11": bolt},
        headers={"Idempotency-Key": secrets.token_hex(16)},
    )
    assert response.status_code == 200, response.text
    return owner, owner_key, a, key_a, b, key_b, cid, gid, prefix, payment_hash


def approve(client, key, prefix):
    response = client.post(prefix + "/payment/approval/options", json={})
    assert response.status_code == 200, response.text
    opts = response.json()
    response = client.post(
        prefix + "/payment/approval/verify",
        json={
            "challenge_id": opts["challenge_id"],
            "credential": key.assertion(opts["options"]["challenge"]),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_verified_receipt_is_unique_and_exact(money):
    app, worker, network = money
    owner, _, cid, request_id = funded(money)
    for _ in range(3):
        worker.tick()
    assert network.create_calls == 1
    assert owner.get(f"/api/clans/{cid}/deposits/{request_id}").json()["status"] == "settled"
    with app.state.security.db() as db:
        assert db.get(Balance, cid).balance_msat == 1_000_000
        assert db.scalar(select(func.count()).select_from(DepositReceipt)) == 1
        assert db.scalar(select(func.count()).select_from(LedgerEntry)) == 1


def test_invoice_creation_timeout_is_reconciled_without_repost(money):
    app, worker, network = money
    network.timeout_create = True
    owner, _, cid, request_id = funded(money)
    assert network.create_calls == 1
    assert owner.get(f"/api/clans/{cid}").json()["balance_msat"] == "1000000"


def test_paid_flag_without_node_proof_cannot_credit(money):
    app, worker, network = money
    network.bad_proof = True
    owner, *_ = signup(app)
    cid = clan(owner)
    response = owner.post(
        f"/api/clans/{cid}/deposits",
        json={"amount_sats": 1000},
        headers={"Idempotency-Key": secrets.token_hex(16)},
    )
    assert response.status_code == 200
    network.paid = True
    worker.tick()
    assert owner.get(f"/api/clans/{cid}").json()["balance_msat"] == "0"
    with app.state.security.db() as db:
        assert db.scalar(select(func.count()).select_from(DepositReceipt)) == 0


def test_exact_signatures_disbursement_fee_and_debt(money):
    app, worker, network = money
    owner, _, a, key_a, b, key_b, cid, gid, prefix, payment_hash = prepared(money)
    assert owner.post(prefix + "/payment/approval/options", json={}).status_code == 409
    assert owner.get(f"/api/clans/{cid}").json()["reserved_msat"] == "101000"
    assert approve(a, key_a, prefix)["status"] == "awaiting_approvals"
    worker.tick()
    assert network.pay_calls == 0
    assert approve(b, key_b, prefix)["status"] == "queued"
    worker.tick()
    worker.tick()
    assert network.pay_calls == 1
    with app.state.security.db() as db:
        assert db.get(Balance, cid).balance_msat == 899877
        assert db.get(Balance, cid).reserved_msat == 0
        assert db.get(Debt, gid).outstanding_msat == 100000
        assert (
            db.scalar(select(Payout).where(Payout.payment_hash == payment_hash)).fee_paid_msat
            == 123
        )
    detail = owner.get(f"/api/clans/{cid}").json()
    assert detail["grants"][0]["status"] == "in_recovery"
    assert detail["available_msat"] == "899877"


def test_lost_payout_response_books_once(money):
    app, worker, network = money
    _, _, a, key_a, b, key_b, cid, gid, prefix, _ = prepared(money)
    approve(a, key_a, prefix)
    approve(b, key_b, prefix)
    network.timeout_send = True
    worker.tick()
    worker.tick()
    assert network.pay_calls == 1
    with app.state.security.db() as db:
        assert db.get(Debt, gid).outstanding_msat == 100000
        assert db.get(Balance, cid).reserved_msat == 0


def test_pending_payment_keeps_reservation_and_never_resends(money):
    app, worker, network = money
    _, _, a, key_a, b, key_b, cid, gid, prefix, payment_hash = prepared(money)
    approve(a, key_a, prefix)
    approve(b, key_b, prefix)
    network.pending_send = True
    worker.tick()
    worker.tick()
    assert network.pay_calls == 1
    with app.state.security.db() as db:
        assert db.get(Debt, gid) is None
        assert db.get(Balance, cid).reserved_msat == 101000
    network.outgoing[payment_hash]["status"] = "Complete"
    worker.tick()
    assert network.pay_calls == 1


def test_previous_external_payment_is_not_charged_to_clan(money):
    app, worker, network = money
    _, _, a, key_a, b, key_b, cid, gid, prefix, payment_hash = prepared(money)
    approve(a, key_a, prefix)
    approve(b, key_b, prefix)
    network.outgoing[payment_hash] = {"status": "Complete"}
    worker.tick()
    assert network.pay_calls == 0
    with app.state.security.db() as db:
        assert db.get(Balance, cid).balance_msat == 1_000_000
        assert db.get(Balance, cid).reserved_msat == 0
        assert db.get(Debt, gid) is None


def test_expired_payment_releases_only_unspent_reservation(money):
    app, worker, network = money
    _, _, a, key_a, b, key_b, cid, _, prefix, _ = prepared(money)
    approve(a, key_a, prefix)
    approve(b, key_b, prefix)
    with app.state.security.db() as db:
        intent = db.scalar(select(PaymentIntent))
        intent.expires_at = "2000-01-01T00:00:00+00:00"
    worker.tick()
    assert network.pay_calls == 0
    with app.state.security.db() as db:
        assert db.get(Balance, cid).reserved_msat == 0


def test_repayment_reduces_actual_debt_and_credits_exact_capital(money):
    app, worker, network = money
    owner, _, a, key_a, b, key_b, cid, gid, prefix, _ = prepared(money)
    approve(a, key_a, prefix)
    approve(b, key_b, prefix)
    worker.tick()
    response = owner.post(
        f"/api/clans/{cid}/deposits",
        json={"amount_sats": 40, "grant_id": gid},
        headers={"Idempotency-Key": secrets.token_hex(16)},
    )
    assert response.status_code == 200, response.text
    worker.tick()
    worker.tick()
    with app.state.security.db() as db:
        debt = db.get(Debt, gid)
        assert debt.outstanding_msat == 60000
        assert debt.recovered_msat == 40000
        assert db.get(Balance, cid).balance_msat == 939877
    home = owner.get(f"/api/clans/{cid}").json()
    assert home["grants_given_msat"] == "100000"
    assert home["grants_repaid_msat"] == "40000"
    assert home["in_recovery_msat"] == "60000"
    borrower_id = b.get("/api/session").json()["user"]["id"]
    old_vote_id = new_id()
    with app.state.security.db() as db:
        source = db.get(Grant, gid)
        common = {
            "clan_id": cid,
            "beneficiary_id": borrower_id,
            "purpose": "Historical request for stock",
            "amount_sats": 1,
            "principal_minor": 1,
            "outstanding_minor": 0,
            "policy_snapshot": source.policy_snapshot,
            "eligible_voters": [source.beneficiary_id],
            "eligible_signers": [],
        }
        db.add_all([Grant(id=new_id(), status="rejected", **common) for _ in range(101)])
        db.add(
            Grant(id=old_vote_id, status="voting", created_at="2000-01-01T00:00:00+00:00", **common)
        )
    older = owner.get(f"/api/clans/{cid}").json()
    visible = {grant["id"]: grant for grant in older["grants"]}
    assert gid in visible and visible[gid]["outstanding_msat"] == "60000"
    assert old_vote_id in visible and visible[old_vote_id]["can_vote"]
    assert len(visible) == 102  # Recent 100 plus old debt and a pending vote.
    assert older["grants_given_msat"] == "100000"
    assert older["grants_repaid_msat"] == "40000"


def test_signed_field_tampering_never_dispatches(money):
    app, worker, network = money
    _, _, a, key_a, b, key_b, _, _, prefix, _ = prepared(money)
    approve(a, key_a, prefix)
    approve(b, key_b, prefix)
    with app.state.security.db() as db:
        intent = db.scalar(select(PaymentIntent))
        intent.canonical = {**intent.canonical, "fee_limit_msat": 900000}
    worker.tick()
    assert network.pay_calls == 0
    with app.state.security.db() as db:
        assert db.get(WorkerStatus, "treasury").status == "unavailable"


def test_mainnet_invoice_validation():
    encoded, _ = invoice(123000)
    assert decode_invoice(encoded)["amount_msat"] == 123000
    with pytest.raises(ProviderError):
        decode_invoice(encoded[:-1] + ("q" if encoded[-1] != "q" else "p"))


def test_recovered_signer_key_requires_fresh_payment_approval(money):
    app, worker, network = money
    _, _, a, key_a, b, key_b, cid, gid, prefix, _ = prepared(money)
    approve(a, key_a, prefix)
    approve(b, key_b, prefix)
    # Recovery revokes old keys. The executor independently checks that state.
    with app.state.security.db() as db:
        old_key = db.scalar(select(Passkey).where(Passkey.credential_id == a_key_id(key_a)))
        old_key.active = False
    worker.tick()
    assert network.pay_calls == 0
    with app.state.security.db() as db:
        assert db.scalar(select(Payout)).status == "awaiting_approvals"
        assert db.get(Debt, gid) is None
        assert db.get(Balance, cid).reserved_msat == 101000


def a_key_id(key):
    from clans.live_security import b64

    return b64(key.id)


def test_forged_saved_signature_cannot_trigger_payment(money):
    app, worker, network = money
    _, _, a, key_a, b, key_b, _, _, prefix, _ = prepared(money)
    approve(a, key_a, prefix)
    approve(b, key_b, prefix)
    with app.state.security.db() as db:
        approval = db.scalar(select(SignerApproval))
        proof = json.loads(json.dumps(approval.assertion))
        proof["credential"]["response"]["signature"] = "AAAA"
        approval.assertion = proof
    worker.tick()
    assert network.pay_calls == 0
    with app.state.security.db() as db:
        assert db.scalar(select(Payout)).status == "awaiting_approvals"


def test_provider_fee_above_approval_never_overcharges_clan(money):
    app, worker, network = money
    _, _, a, key_a, b, key_b, cid, _, prefix, payment_hash = prepared(money)
    approve(a, key_a, prefix)
    approve(b, key_b, prefix)
    original = network.handle

    def excessive_fee(request):
        result = original(request)
        if request.url.path.endswith("/payments/" + payment_hash) and result.status_code == 200:
            data = result.json()
            if data.get("status") == "Complete":
                data.update(feeAmount="2000", totalAmount="102000")
                return httpx.Response(200, json=data)
        return result

    worker.provider.client.close()
    worker.provider = TreasuryProvider(
        worker.settings, transport=httpx.MockTransport(excessive_fee)
    )
    worker.tick()
    with app.state.security.db() as db:
        assert db.get(Balance, cid).balance_msat == 899000
        assert db.scalar(select(Payout)).last_error == "operator_fee_excess_requires_review"
        assert db.get(WorkerStatus, "treasury").status == "unavailable"
