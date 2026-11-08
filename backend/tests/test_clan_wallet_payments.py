"""Clan wallet money: addresses, receipts, payout drafts, signatures and the chain watcher.

A fake chain stands in for the block explorer, so no test touches a network. Payments are
real BDK transactions signed with test keys, exactly as phones and the oversight tool do.
"""

import base64
import json
import math
import secrets
import struct
from datetime import UTC, datetime, timedelta

import bdkpython as bdk
import pytest
from clan_wallet_helpers import DESTINATION, OTHER_DESTINATION, secret_key, sign_normal_path
from fastapi.testclient import TestClient
from role_grants import GrantChecker
from sqlalchemy import func, select
from test_clan_wallet_api import make_app, phone_code, three_signer_clan
from test_live_app import ORIGIN, signup

from clans.chain_watcher import ChainWatcher, TxState
from clans.clan_wallet import ClanPolicy, ClanWallet, ClanWalletError, Recipient
from clans.money_models import Balance, Debt, LedgerEntry
from clans.wallet_models import (
    ClanWalletRecord,
    WalletAlarm,
    WalletPayout,
    WalletReceipt,
    WalletSignature,
)
from clans.wallet_payments import (
    key_origins,
    only_signatures_from,
    psbt_details,
    signature_set,
)

GRANT_SATS = 40_000


class FakeChain:
    """A test network: payments appear when added and confirm when mined."""

    def __init__(self, network=bdk.Network.SIGNET):
        self.tip, self.rate, self.counter = 100, 2, 0
        self.network = network
        self.txs: dict[str, dict] = {}
        self.broadcasts: list[str] = []

    def tip_height(self):
        return self.tip

    def fee_rate(self):
        return self.rate

    def add(self, tx: bdk.Transaction) -> str:
        txid = str(tx.compute_txid())
        self.counter += 1
        self.txs[txid] = {"tx": tx, "height": None, "present": True, "seen": self.counter}
        return txid

    def pay(self, address: str, amount_sats: int) -> str:
        """Someone outside the clan sends money to an address."""
        self.counter += 1
        script = bytes(bdk.Address(address, self.network).script_pubkey().to_bytes())
        raw = (
            struct.pack("<I", 2)
            + b"\x01"
            + self.counter.to_bytes(32, "little")
            + struct.pack("<I", 0)
            + b"\x00"
            + b"\xff\xff\xff\xff"
            + b"\x01"
            + struct.pack("<Q", amount_sats)
            + bytes([len(script)])
            + script
            + struct.pack("<I", 0)
        )
        return self.add(bdk.Transaction(raw))

    def mine(self, txid: str, blocks: int = 3):
        """Confirm a payment and add blocks until it has `blocks` confirmations."""
        self.txs[txid]["height"] = self.tip
        self.tip += blocks - 1

    def drop(self, txid: str):
        self.counter += 1
        self.txs[txid].update(present=False, evicted=self.counter)

    def sync(self, wallet: ClanWallet):
        present = [e for e in self.txs.values() if e["present"]]
        wallet.wallet.apply_unconfirmed_txs(
            [bdk.UnconfirmedTx(tx=e["tx"], last_seen=e["seen"]) for e in present]
        )
        wallet.wallet.apply_evicted_txs(
            [
                bdk.EvictedTx(txid=bdk.Txid.from_string(txid), evicted_at=e["evicted"])
                for txid, e in self.txs.items()
                if not e["present"]
            ]
        )

    def state(self, txid: str) -> TxState:
        entry = self.txs.get(txid)
        if not entry or not entry["present"]:
            return TxState(False)
        return TxState(True, entry["height"])

    def broadcast(self, raw_hex: str):
        self.broadcasts.append(self.add(bdk.Transaction(bytes.fromhex(raw_hex))))


@pytest.fixture(scope="module")
def keys():
    return [str(secret_key(seed).as_public()) for seed in range(1, 6)]


@pytest.fixture
def clan(tmp_path, keys):
    """An active 3-signatory clan wallet. Oversight is key 1; signatories hold keys 2-4.

    Every statement is checked against the production grants: the web app's as the web
    role, the chain watcher's as the worker role.
    """
    app = make_app(tmp_path, keys)
    grants = GrantChecker()
    grants.watch(app.state.security.engine, "web")
    cid, signers, member = three_signer_clan(app)
    route = f"/api/clans/{cid}/wallet"
    for client, key in zip(signers, keys[1:4], strict=True):
        assert client.post(route + "/keys", json={"key": key}).status_code == 200
    view = signers[0].get(route).json()
    for client in signers:
        assert client.post(route + "/confirm", json={"wallet_code": phone_code(view)}).is_success
    view = signers[0].get(route).json()
    assert view["status"] == "active"
    policy = ClanPolicy.create(
        network="signet",
        oversight=view["policy"]["oversight"],
        signers=view["policy"]["signers"],
    )
    chain = FakeChain()
    watcher = ChainWatcher(app.state.security.settings, chain=chain)
    grants.watch(watcher.security.engine, "worker")
    secrets_by_client = {
        id(c): secret_key(seed) for c, seed in zip(signers, (2, 3, 4), strict=True)
    }
    state = {
        "app": app,
        "cid": cid,
        "signers": signers,
        "member": member,
        "policy": policy,
        "chain": chain,
        "watcher": watcher,
        "secret": lambda c: secrets_by_client[id(c)],
        "grants": grants,
    }
    yield state
    grants.assert_clean()
    watcher.security.engine.dispose()
    app.state.security.engine.dispose()


def tick(clan):
    """A cycle that reads every wallet, as after a new block. test_chain_reads covers the rest."""
    clan["watcher"].last_read.clear()
    clan["watcher"].tick()
    assert clan["watcher"].failures == {}


def address(client, cid, purpose, grant_id=None):
    query = f"purpose={purpose}" + (f"&grant_id={grant_id}" if grant_id else "")
    response = client.get(f"/api/clans/{cid}/wallet/address?{query}")
    assert response.status_code == 200, response.text
    return response.json()


def balance_msat(clan):
    with clan["app"].state.security.db() as db:
        value = db.get(Balance, clan["cid"])
        return value.balance_msat, value.reserved_msat


def fund_clan(clan, amount_sats):
    main = address(clan["signers"][0], clan["cid"], "grant_funding")["address"]
    txid = clan["chain"].pay(main, amount_sats)
    clan["chain"].mine(txid)
    tick(clan)
    return txid


def accepted_grant(clan, amount_sats=GRANT_SATS):
    owner, second, third = clan["signers"]
    cid = clan["cid"]
    response = owner.post(
        f"/api/clans/{cid}/grants",
        json={"purpose": "Stock for the shop", "amount_sats": amount_sats},
        headers={"Idempotency-Key": secrets.token_hex(16)},
    )
    assert response.status_code == 200, response.text
    gid = response.json()["grant_id"]
    route = f"/api/clans/{cid}/grants/{gid}"
    for voter in (second, third):
        assert voter.post(route + "/vote", json={"choice": "approve"}).status_code == 200
    assert owner.post(route + "/accept", json={}).status_code == 200
    return gid


def drafts(client, cid, **query):
    response = client.get(f"/api/clans/{cid}/wallet/payouts", params=query)
    assert response.status_code == 200, response.text
    return response.json()


def sign(clan, client, payout):
    signed = sign_normal_path(clan["policy"], clan["secret"](client), payout["psbt"])
    route = f"/api/clans/{clan['cid']}/wallet/payouts/{payout['id']}/signature"
    return client.post(route, json={"psbt": signed})


def oversight_sign(clan, payout, key=None):
    signed = sign_normal_path(clan["policy"], key or secret_key(1), payout["psbt"])
    tool = TestClient(clan["app"], base_url=ORIGIN)
    route = f"/api/clans/{clan['cid']}/wallet/payouts/{payout['id']}/oversight-signature"
    return tool.post(route, json={"psbt": signed})


def ready_payout(clan):
    """Fund the clan, pass a grant and give the beneficiary's address. Returns the draft."""
    fund_clan(clan, 100_000)
    gid = accepted_grant(clan)
    owner = clan["signers"][0]
    response = owner.post(
        f"/api/clans/{clan['cid']}/grants/{gid}/payout-address", json={"address": DESTINATION}
    )
    assert response.status_code == 200, response.text
    tick(clan)
    (payout,) = drafts(owner, clan["cid"], grant_id=gid)
    return gid, payout


def test_addresses_come_from_the_clan_wallet_and_are_reused(clan):
    owner, second, _ = clan["signers"]
    cid, wallet = clan["cid"], ClanWallet(clan["policy"])
    main = address(owner, cid, "grant_funding")
    assert main == {
        "address": wallet.address(0),
        "keychain": "external",
        "index": 0,
        "purpose": "grant_funding",
        "grant_id": None,
    }
    mine = address(owner, cid, "contribution")
    assert mine["index"] == 1 and mine["address"] == wallet.address(1)
    assert address(owner, cid, "contribution") == mine
    assert address(second, cid, "contribution")["index"] == 2
    assert address(clan["member"], cid, "grant_funding") == main
    route = f"/api/clans/{cid}/wallet/address"
    assert owner.get(route + "?purpose=repayment").status_code == 422
    assert owner.get(route + "?purpose=contribution&grant_id=x").status_code == 422
    assert owner.get(route + "?purpose=savings").status_code == 422
    gid = accepted_grant(clan)
    # No repayment address until the grant has been paid out.
    assert owner.get(route + f"?purpose=repayment&grant_id={gid}").status_code == 409


def test_deposits_count_only_after_three_confirmations(clan):
    owner, chain, cid = clan["signers"][0], clan["chain"], clan["cid"]
    mine = address(owner, cid, "contribution")["address"]
    txid = chain.pay(mine, 50_000)
    tick(clan)
    (receipt,) = owner.get(f"/api/clans/{cid}/wallet/receipts?address={mine}").json()
    assert receipt["id"] == f"{txid}:0" and receipt["status"] == "pending"
    assert receipt["amount_sats"] == 50_000 and receipt["purpose"] == "contribution"
    assert balance_msat(clan) == (0, 0)
    chain.mine(txid, blocks=2)
    tick(clan)
    assert owner.get(f"/api/clans/{cid}/wallet/receipts").json()[0]["confirmations"] == 2
    assert balance_msat(clan) == (0, 0)
    chain.tip += 1
    tick(clan)
    tick(clan)
    (receipt,) = owner.get(f"/api/clans/{cid}/wallet/receipts").json()
    assert receipt["status"] == "confirmed" and receipt["confirmations"] == 3
    assert balance_msat(clan) == (50_000_000, 0)
    with clan["app"].state.security.db() as db:
        assert db.scalar(select(func.count()).select_from(LedgerEntry)) == 1
    # Another member sees nothing of their own, but can look up the clan address.
    assert clan["member"].get(f"/api/clans/{cid}/wallet/receipts").json() == []
    # A payment that leaves the network before confirming is never credited.
    gone = chain.pay(mine, 7_000)
    tick(clan)
    chain.drop(gone)
    tick(clan)
    statuses = {
        r["txid"]: r["status"] for r in owner.get(f"/api/clans/{cid}/wallet/receipts").json()
    }
    assert statuses[gone] == "dropped"
    assert balance_msat(clan) == (50_000_000, 0)


def test_grant_is_paid_after_the_clan_and_oversight_sign(clan):
    owner, second, third = clan["signers"]
    cid, chain = clan["cid"], clan["chain"]
    route = f"/api/clans/{cid}/grants"
    # Quotes need the chain watcher's fee rate.
    fund_clan(clan, 100_000)
    gid = accepted_grant(clan)
    quote = owner.get(f"{route}/{gid}/payout-quote?address={DESTINATION}")
    assert quote.status_code == 200, quote.text
    assert quote.json() == {
        "address": DESTINATION,
        "approved_sats": GRANT_SATS,
        "fee_paid_by": "recipients",
        "estimated_fee_sats": 452,
        "estimated_received_sats": GRANT_SATS - 452,
        "fee_rate_sat_vb": 2,
    }
    assert second.get(f"{route}/{gid}/payout-quote?address={DESTINATION}").status_code == 403
    own = address(owner, cid, "contribution")["address"]
    for wrong in (own, "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4", "tb1qnotanaddress"):
        response = owner.get(f"{route}/{gid}/payout-quote", params={"address": wrong})
        assert response.status_code == 400, wrong
    assert owner.post(f"{route}/{gid}/payout-address", json={"address": DESTINATION}).is_success
    assert balance_msat(clan) == (100_000_000, GRANT_SATS * 1000)
    tick(clan)
    (payout,) = drafts(owner, cid, grant_id=gid)
    assert payout["status"] == "awaiting_signatures"
    assert payout["recipients"] == [
        {
            "grant_id": gid,
            "name": "Organizer",
            "address": DESTINATION,
            "approved_sats": GRANT_SATS,
            "received_sats": GRANT_SATS - payout["fee_sats"],
        }
    ]
    # What a phone checks before signing: the payment matches the listed recipients.
    ClanWallet(clan["policy"]).check_payout(
        payout["psbt"],
        [Recipient(DESTINATION, GRANT_SATS)],
        max_fee_sats=payout["max_fee_sats"],
        fee_paid_by="recipients",
    )
    assert sign(clan, owner, payout).status_code == 403  # the beneficiary can't sign
    assert (
        clan["member"]
        .post(
            f"/api/clans/{cid}/wallet/payouts/{payout['id']}/signature",
            json={"psbt": payout["psbt"]},
        )
        .status_code
        == 403
    )
    first = sign(clan, second, payout)
    assert first.status_code == 200, first.text
    assert first.json()["signatures"] == {
        "count": 1,
        "required": 2,
        "signed_by_me": True,
        "names": ["Second Signer"],
    }
    view = sign(clan, third, first.json()).json()
    assert view["status"] == "awaiting_oversight"
    tick(clan)
    assert chain.broadcasts == []
    # A signatory's key can't be used as an oversight signature.
    refused = oversight_sign(clan, view, key=secret_key(2))
    assert refused.status_code == 409
    approved = oversight_sign(clan, view)
    assert approved.status_code == 200, approved.text
    assert approved.json()["oversight_signed"] is True
    assert drafts(owner, cid, grant_id=gid)[0]["status"] == "broadcasting"
    tick(clan)
    assert chain.broadcasts == [payout["txid"]]
    (sent,) = drafts(owner, cid, status="broadcast")
    assert sent["broadcast_txid"] == payout["txid"]
    assert owner.get(f"/api/clans/{cid}").json()["grants"][0]["status"] == "paying"
    # Signing after it was sent is refused.
    assert sign(clan, second, sent).status_code == 409
    chain.mine(payout["txid"])
    tick(clan)
    (done,) = drafts(owner, cid, status="confirmed,broadcast")
    assert done["status"] == "confirmed" and done["confirmations"] == 3
    assert balance_msat(clan) == (100_000_000 - GRANT_SATS * 1000, 0)
    with clan["app"].state.security.db() as db:
        debt = db.get(Debt, gid)
        assert debt.principal_msat == debt.outstanding_msat == GRANT_SATS * 1000
        assert db.scalar(select(func.count()).select_from(WalletAlarm)) == 0
    # The beneficiary repays to the grant's own address.
    repay = address(owner, cid, "repayment", gid)
    txid = chain.pay(repay["address"], 15_000)
    chain.mine(txid)
    tick(clan)
    (receipt,) = owner.get(f"/api/clans/{cid}/wallet/receipts").json()
    assert receipt["grant_id"] == gid and receipt["status"] == "confirmed"
    with clan["app"].state.security.db() as db:
        assert db.get(Debt, gid).outstanding_msat == (GRANT_SATS - 15_000) * 1000
    assert balance_msat(clan) == ((100_000 - GRANT_SATS + 15_000) * 1000, 0)


def forge(signed: str) -> str:
    """The same signed copy with one bit of the first signature flipped."""
    details = json.loads(bdk.Psbt(signed).json_serialize())
    signature = bytes.fromhex(details["inputs"][0]["tap_script_sigs"][0][1]["signature"])
    raw = bytearray(base64.b64decode(signed))
    raw[raw.find(signature) + 5] ^= 1
    return base64.b64encode(bytes(raw)).decode()


def test_a_forged_signature_is_refused_when_uploaded(clan):
    _, second, third = clan["signers"]
    _, payout = ready_payout(clan)
    forged = forge(sign_normal_path(clan["policy"], clan["secret"](second), payout["psbt"]))
    route = f"/api/clans/{clan['cid']}/wallet/payouts/{payout['id']}/signature"
    response = second.post(route, json={"psbt": forged})
    assert response.status_code == 409 and "doesn't match" in response.json()["detail"]
    # Anyone can reach the oversight route, so a forgery there must not replace a good one.
    view = sign(clan, second, payout).json()
    view = sign(clan, third, view).json()
    assert oversight_sign(clan, view).status_code == 200
    good = sign_normal_path(clan["policy"], secret_key(1), view["psbt"])
    tool = TestClient(clan["app"], base_url=ORIGIN)
    oversight_route = route.replace("/signature", "/oversight-signature")
    response = tool.post(oversight_route, json={"psbt": forge(only_oversight(clan, good))})
    assert response.status_code == 409
    tick(clan)
    assert clan["chain"].broadcasts == [payout["txid"]]


def only_oversight(clan, signed):
    origins = key_origins(psbt_details(signed))
    fingerprint = clan["policy"].oversight[0].fingerprint
    return only_signatures_from(signed, {x for x, (fp, _) in origins.items() if fp == fingerprint})


def test_a_bad_signature_is_caught_before_broadcast(clan):
    _, second, third = clan["signers"]
    _, payout = ready_payout(clan)
    signed = sign_normal_path(clan["policy"], clan["secret"](second), payout["psbt"])
    assert sign(clan, second, payout).status_code == 200
    # Suppose a forged copy got into the database anyway: the chain watcher still catches it.
    with clan["app"].state.security.db() as db:
        row = db.scalar(select(WalletSignature).where(WalletSignature.payout_id == payout["id"]))
        row.psbt = forge(signed)
    view = sign(clan, third, payout).json()
    assert oversight_sign(clan, view).status_code == 200
    tick(clan)
    assert clan["chain"].broadcasts == []
    (current,) = drafts(third, clan["cid"])
    assert current["status"] == "awaiting_signatures"
    assert current["signatures"]["names"] == ["Third Signer"]
    with clan["app"].state.security.db() as db:
        assert db.scalar(select(WalletAlarm.kind)) == "invalid_signature"
        assert db.scalar(select(func.count()).select_from(WalletSignature)) == 3
    # Signing again with a good signature lets the payout go out.
    again = sign(clan, second, current)
    assert again.status_code == 200, again.text
    tick(clan)
    assert clan["chain"].broadcasts == [payout["txid"]]


def test_only_your_own_signature_on_this_payment_is_accepted(clan):
    owner, second, third = clan["signers"]
    _, payout = ready_payout(clan)
    route = f"/api/clans/{clan['cid']}/wallet/payouts/{payout['id']}/signature"
    # A copy carrying another signatory's signature, as if one person signed for two.
    both = sign_normal_path(clan["policy"], clan["secret"](third), payout["psbt"])
    both = sign_normal_path(clan["policy"], clan["secret"](second), both)
    response = second.post(route, json={"psbt": both})
    assert response.status_code == 409 and "other keys" in response.json()["detail"]
    # The unsigned copy adds nothing.
    response = second.post(route, json={"psbt": payout["psbt"]})
    assert response.status_code == 409
    # A signature for a different payment.
    other = ClanWallet(clan["policy"])
    clan["chain"].sync(other)
    elsewhere = other.build_payout(
        [Recipient(OTHER_DESTINATION, 20_000)],
        fee_rate_sat_vb=3,
        max_fee_sats=3_000,
        fee_paid_by="recipients",
        allow_unconfirmed=True,
    )
    signed = sign_normal_path(clan["policy"], clan["secret"](second), elsewhere.psbt)
    response = second.post(route, json={"psbt": signed})
    assert response.status_code == 409 and "different payment" in response.json()["detail"]
    garbage = base64.b64encode(b"this is not a payment at all").decode()
    assert second.post(route, json={"psbt": garbage}).status_code == 409


def test_a_new_address_spends_the_same_coins(clan):
    owner, second, _ = clan["signers"]
    cid = clan["cid"]
    gid, first = ready_payout(clan)
    assert sign(clan, second, first).status_code == 200
    # More money arrives, so a fresh payout could pick different coins.
    fund_clan(clan, 300_000)
    response = owner.post(
        f"/api/clans/{cid}/grants/{gid}/payout-address", json={"address": OTHER_DESTINATION}
    )
    assert response.status_code == 200, response.text
    assert balance_msat(clan)[1] == GRANT_SATS * 1000  # still held once
    tick(clan)
    versions = {p["id"]: p for p in drafts(owner, cid, grant_id=gid)}
    old, new = versions[first["id"]], next(p for p in versions.values() if p["id"] != first["id"])
    assert old["status"] == "expired" and old["replaced_by"] == new["id"]
    assert new["replaces"] == old["id"] and new["recipients"][0]["address"] == OTHER_DESTINATION
    with clan["app"].state.security.db() as db:
        assert db.get(WalletPayout, old["id"]).inputs == db.get(WalletPayout, new["id"]).inputs
    response = sign(clan, second, old)
    assert response.status_code == 409 and "replaced" in response.json()["detail"]


def rogue_spend(clan):
    """Someone with every key spends without going through Clans. Returns the txid."""
    rogue = ClanWallet(clan["policy"])
    clan["chain"].sync(rogue)
    draft = rogue.build_payout(
        [Recipient(OTHER_DESTINATION, 50_000)],
        fee_rate_sat_vb=2,
        max_fee_sats=3_000,
        allow_unconfirmed=True,
    )
    copies = [sign_normal_path(clan["policy"], secret_key(seed), draft.psbt) for seed in (1, 2, 3)]
    sent = rogue.finalize(
        draft.psbt, copies, [Recipient(OTHER_DESTINATION, 50_000)], max_fee_sats=3_000
    )
    clan["chain"].add(bdk.Transaction(bytes.fromhex(sent.raw_hex)))
    tick(clan)
    tick(clan)
    return sent.txid


def test_money_leaving_without_a_payout_raises_an_alarm(clan):
    fund_clan(clan, 100_000)
    txid = rogue_spend(clan)
    with clan["app"].state.security.db() as db:
        alarms = db.scalars(select(WalletAlarm)).all()
        assert [(a.kind, a.reference) for a in alarms] == [("unapproved_spend", txid)]


def afribit_only_alarm(clan):
    """An operational alarm members don't see, written as the chain watcher would."""
    with clan["grants"].paused(), clan["app"].state.security.db() as db:
        wallet = db.scalar(select(ClanWalletRecord).where(ClanWalletRecord.clan_id == clan["cid"]))
        db.add(WalletAlarm(wallet_id=wallet.id, kind="sweep_blocked", reference="test", detail={}))
        db.commit()


def test_members_see_the_alarms_about_their_money(clan, tmp_path):
    owner = clan["signers"][0]
    route = f"/api/clans/{clan['cid']}/wallet"
    assert owner.get(route + "/alarms").json() == []
    assert owner.get(route).json()["alarms_recent"] == 0
    fund_clan(clan, 100_000)
    txid = rogue_spend(clan)
    afribit_only_alarm(clan)

    (shown,) = clan["member"].get(route + "/alarms").json()  # every member, not only signers
    assert shown["kind"] == "unapproved_spend" and shown["members"] is True
    assert shown["reference"] == txid and shown["generation"] == 1
    assert "without an approved payout" in shown["message"]
    assert owner.get(route).json()["alarms_recent"] == 1

    outsider, *_ = signup(clan["app"], "Someone Else")
    assert outsider.get(route + "/alarms").status_code == 403


def test_afribit_sees_every_alarm_and_only_new_ones(clan, tmp_path):
    from clans import oversight

    home, _ = oversight_laptop(clan, tmp_path)
    clan["app"].state.security.settings.clan_wallet_oversight_token_hashes = oversight.connect(
        home, ORIGIN
    )
    token = json.loads((home / oversight.SERVER_FILE).read_text(encoding="utf-8"))["token"]
    laptop = TestClient(clan["app"], base_url=ORIGIN, headers={"Authorization": "Bearer " + token})
    anonymous = TestClient(clan["app"], base_url=ORIGIN)
    assert anonymous.get("/api/oversight/alarms").status_code == 401
    assert laptop.get("/api/oversight/alarms?since=yesterday").status_code == 422

    fund_clan(clan, 100_000)
    rogue_spend(clan)
    afribit_only_alarm(clan)
    found = oversight.unread_alarms(home, laptop)
    assert sorted(item["kind"] for item in found) == ["sweep_blocked", "unapproved_spend"]
    assert {item["clan_name"] for item in found} == {"Real Treasury"}

    oversight.mark_alarms_read(home, found)
    assert oversight.unread_alarms(home, laptop) == []
    assert len(oversight.alarms(laptop)) == 2
    # A time without a zone is UTC; an old one returns everything.
    assert len(laptop.get("/api/oversight/alarms?since=2026-01-01T00:00:00").json()) == 2


def test_payout_routes_need_an_active_wallet_and_chain_data(tmp_path, keys):
    app = make_app(tmp_path, keys)
    cid, signers, _ = three_signer_clan(app)
    owner = signers[0]
    assert owner.get(f"/api/clans/{cid}/wallet/address?purpose=grant_funding").status_code == 409
    assert owner.get(f"/api/clans/{cid}/wallet/payouts").json() == []
    assert owner.get(f"/api/clans/{cid}/wallet/receipts").json() == []
    app.state.security.engine.dispose()
    (tmp_path / "off").mkdir()
    off = make_app(tmp_path / "off", keys, enabled=False)
    cid, signers, _ = three_signer_clan(off)
    response = signers[0].get(f"/api/clans/{cid}/wallet/address?purpose=grant_funding")
    assert response.status_code == 503
    off.state.security.engine.dispose()


def test_quotes_wait_for_the_chain_watcher(clan):
    owner = clan["signers"][0]
    gid = accepted_grant(clan)
    route = f"/api/clans/{clan['cid']}/grants/{gid}/payout-quote?address={DESTINATION}"
    assert owner.get(route).status_code == 503
    tick(clan)
    assert owner.get(route).status_code == 200
    with clan["app"].state.security.db() as db:
        assert db.scalar(select(func.count()).select_from(WalletReceipt)) == 0
    # Without confirmed money the address can't be given.
    response = owner.post(
        f"/api/clans/{clan['cid']}/grants/{gid}/payout-address", json={"address": DESTINATION}
    )
    assert response.status_code == 409 and "confirmed money" in response.json()["detail"]


def test_each_stored_copy_holds_only_its_own_signatures(clan):
    _, second, third = clan["signers"]
    _, payout = ready_payout(clan)
    view = sign(clan, second, payout).json()
    view = sign(clan, third, view).json()
    # The oversight copy is made from the combined payment, with both clan signatures in it.
    assert oversight_sign(clan, view).status_code == 200
    with clan["app"].state.security.db() as db:
        origins = key_origins(psbt_details(payout["psbt"]))
        for row in db.scalars(select(WalletSignature)):
            found = signature_set(psbt_details(row.psbt))
            assert found and {origins[xonly][0] for _, xonly, _, _ in found} == {row.fingerprint}
    combined = drafts(second, clan["cid"])[0]["psbt"]
    assert len(signature_set(psbt_details(combined))) == 3
    assert only_signatures_from(combined, set()) != combined
    assert signature_set(psbt_details(only_signatures_from(combined, set()))) == set()


def test_the_oversight_tool_signs_the_draft_as_served(clan, tmp_path):
    from clans import oversight

    owner, second, third = clan["signers"]
    passphrase = "correct horse battery staple"
    home = tmp_path / "oversight"
    _, public = oversight.create_key(
        home, passphrase, str(bdk.Mnemonic.from_entropy(bytes([1]) * 16))
    )
    wallet_view = owner.get(f"/api/clans/{clan['cid']}/wallet").json()
    assert public in wallet_view["policy"]["oversight"]
    oversight.add_wallet(home, clan["cid"], wallet_view, clan["policy"].wallet_code())
    start, end = oversight.check_characters(DESTINATION)
    oversight.confirm_address(home, DESTINATION, "Organizer", start, end)
    _, payout = ready_payout(clan)
    view = sign(clan, second, payout).json()
    view = sign(clan, third, view).json()
    signed, complete = oversight.sign(home, view, passphrase)
    assert complete
    tool = TestClient(clan["app"], base_url=ORIGIN)
    route = f"/api/clans/{clan['cid']}/wallet/payouts/{payout['id']}/oversight-signature"
    # The tool's signed file is uploaded as it is, and must name this payout.
    upload = {"id": view["id"], "clan_id": clan["cid"], "txid": view["txid"], "psbt": signed}
    response = tool.post(route, json={**upload, "txid": "0" * 64})
    assert response.status_code == 409 and "different payout" in response.json()["detail"]
    assert tool.post(route, json=upload).status_code == 200
    tick(clan)
    assert clan["chain"].broadcasts == [payout["txid"]]


def test_signature_checks_cover_every_coin_spent(keys):
    from clans.wallet_payments import check_signatures

    policy = ClanPolicy.create(network="signet", oversight=keys[0], signers=keys[1:4])
    wallet, chain = ClanWallet(policy), FakeChain()
    chain.pay(wallet.address(0), 50_000)
    chain.pay(wallet.address(1), 30_000)
    chain.sync(wallet)
    draft = wallet.build_payout(
        [Recipient(DESTINATION, 60_000)],
        fee_rate_sat_vb=2,
        max_fee_sats=3_000,
        allow_unconfirmed=True,
    )
    base = psbt_details(draft.psbt)
    assert len(base["inputs"]) == 2
    signed = sign_normal_path(policy, secret_key(2), draft.psbt)
    assert len(signature_set(psbt_details(signed))) == 2
    check_signatures(psbt_details(signed), base)
    with pytest.raises(ClanWalletError, match="doesn't match"):
        check_signatures(psbt_details(forge(signed)), base)
    # A valid signature checked against a different payment fails.
    other = wallet.build_payout(
        [Recipient(OTHER_DESTINATION, 60_000)],
        fee_rate_sat_vb=2,
        max_fee_sats=3_000,
        allow_unconfirmed=True,
    )
    with pytest.raises(ClanWalletError):
        check_signatures(psbt_details(signed), psbt_details(other.psbt))


def oversight_laptop(clan, tmp_path):
    """An oversight laptop with the clan registered and the beneficiary's address confirmed."""
    from clans import oversight

    passphrase = "correct horse battery staple"
    home = tmp_path / "laptop"
    oversight.create_key(home, passphrase, str(bdk.Mnemonic.from_entropy(bytes([1]) * 16)))
    wallet_view = clan["signers"][0].get(f"/api/clans/{clan['cid']}/wallet").json()
    oversight.add_wallet(home, clan["cid"], wallet_view, clan["policy"].wallet_code())
    start, end = oversight.check_characters(DESTINATION)
    oversight.confirm_address(home, DESTINATION, "Organizer", start, end)
    return home, passphrase


def test_the_oversight_laptop_downloads_signs_and_uploads(clan, tmp_path, monkeypatch):
    from clans import oversight

    _, second, third = clan["signers"]
    home, passphrase = oversight_laptop(clan, tmp_path)
    anonymous = TestClient(clan["app"], base_url=ORIGIN)
    assert anonymous.get("/api/oversight/payouts").status_code == 503  # not set up
    with pytest.raises(oversight.OversightError):
        oversight.connect(home, "http://clans.example.org")
    with pytest.raises(oversight.OversightError):
        oversight.connect(home, "https://clans.example.org/app")
    digest = oversight.connect(home, ORIGIN)
    clan["app"].state.security.settings.clan_wallet_oversight_token_hashes = digest
    token = json.loads((home / oversight.SERVER_FILE).read_text(encoding="utf-8"))["token"]
    assert digest not in token and len(token) >= 40
    assert anonymous.get("/api/oversight/payouts").status_code == 401
    wrong = {"Authorization": "Bearer " + "x" * 43}
    assert anonymous.get("/api/oversight/payouts", headers=wrong).status_code == 401
    laptop = TestClient(clan["app"], base_url=ORIGIN, headers={"Authorization": "Bearer " + token})

    _, payout = ready_payout(clan)
    view = sign(clan, second, payout).json()
    assert oversight.pending(laptop) == []  # the clan hasn't finished signing
    sign(clan, third, view)
    (waiting,) = oversight.pending(laptop)
    assert waiting["id"] == payout["id"] and waiting["status"] == "awaiting_oversight"
    assert waiting["signatures"]["signed_by_me"] is False

    monkeypatch.setattr(oversight, "server", lambda _: laptop)
    monkeypatch.setattr(oversight.getpass, "getpass", lambda _: passphrase)
    # New alarms come first. Stopping there signs nothing and keeps them unread.
    afribit_only_alarm(clan)
    monkeypatch.setattr("builtins.input", lambda _: "no")
    assert oversight.main(["--home", str(home), "approve"]) == 2
    assert len(oversight.pending(laptop)) == 1
    assert len(oversight.unread_alarms(home, laptop)) == 1
    monkeypatch.setattr("builtins.input", lambda _: "yes")
    assert oversight.main(["--home", str(home), "approve"]) == 0
    assert oversight.unread_alarms(home, laptop) == []
    assert oversight.pending(laptop) == []
    tick(clan)
    assert clan["chain"].broadcasts == [payout["txid"]]


def sent_payout(clan):
    """A grant payout signed by the clan and Afribit and broadcast, but not yet confirmed."""
    _, second, third = clan["signers"]
    gid, payout = ready_payout(clan)
    view = sign(clan, second, payout).json()
    view = sign(clan, third, view).json()
    assert oversight_sign(clan, view).status_code == 200
    tick(clan)
    assert clan["chain"].broadcasts == [payout["txid"]]
    return gid, payout


def make_stuck(clan, payout_id, hours=4):
    # Test setup: winds the clock back, as no production role could.
    with clan["grants"].paused(), clan["app"].state.security.db() as db:
        stored = db.get(WalletPayout, payout_id)
        stored.broadcast_at = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()


def test_a_stuck_payout_gets_a_higher_fee_version_to_sign(clan):
    owner, second, third = clan["signers"]
    cid = clan["cid"]
    gid, first = sent_payout(clan)
    clan["chain"].rate = 6
    tick(clan)
    assert len(drafts(owner, cid, grant_id=gid)) == 1  # sent recently: wait
    make_stuck(clan, first["id"])
    tick(clan)
    tick(clan)  # only one new version at a time
    versions = {p["id"]: p for p in drafts(owner, cid, grant_id=gid)}
    assert len(versions) == 2
    new = next(p for p in versions.values() if p["id"] != first["id"])
    assert versions[first["id"]]["status"] == "broadcast"
    assert new["status"] == "awaiting_signatures" and new["replaces"] == first["id"]
    assert new["fee_sats"] > first["fee_sats"] + 200
    # The beneficiary pays the fee, so they receive a little less.
    assert new["recipients"][0]["received_sats"] == GRANT_SATS - new["fee_sats"]
    with clan["app"].state.security.db() as db:
        assert db.get(WalletPayout, new["id"]).inputs == db.get(WalletPayout, first["id"]).inputs
    # It needs everyone's signatures again.
    view = sign(clan, second, new).json()
    view = sign(clan, third, view).json()
    tick(clan)
    assert clan["chain"].broadcasts == [first["txid"]]
    assert oversight_sign(clan, view).status_code == 200
    tick(clan)
    assert clan["chain"].broadcasts == [first["txid"], new["txid"]]
    versions = {p["id"]: p for p in drafts(owner, cid, grant_id=gid)}
    assert versions[first["id"]]["status"] == "replaced"
    assert versions[first["id"]]["replaced_by"] == new["id"]
    # The network drops the old version and confirms the new one.
    clan["chain"].drop(first["txid"])
    clan["chain"].mine(new["txid"])
    tick(clan)
    assert {p["id"]: p["status"] for p in drafts(owner, cid, grant_id=gid)} == {
        first["id"]: "replaced",
        new["id"]: "confirmed",
    }
    with clan["app"].state.security.db() as db:
        assert db.get(Debt, gid).outstanding_msat == GRANT_SATS * 1000
    assert balance_msat(clan) == ((100_000 - GRANT_SATS) * 1000, 0)


def test_a_higher_fee_version_is_dropped_if_the_first_confirms(clan):
    owner, second, _ = clan["signers"]
    cid = clan["cid"]
    gid, first = sent_payout(clan)
    clan["chain"].rate = 6
    make_stuck(clan, first["id"])
    tick(clan)
    (new,) = [p for p in drafts(owner, cid, grant_id=gid) if p["id"] != first["id"]]
    clan["chain"].mine(first["txid"])
    tick(clan)
    statuses = {p["id"]: (p["status"], p["replaced_by"]) for p in drafts(owner, cid, grant_id=gid)}
    assert statuses == {first["id"]: ("confirmed", None), new["id"]: ("replaced", first["id"])}
    response = sign(clan, second, new)
    assert response.status_code == 409 and "replaced" in response.json()["detail"]


def test_no_higher_fee_version_while_fees_are_unchanged(clan):
    owner = clan["signers"][0]
    gid, first = sent_payout(clan)
    make_stuck(clan, first["id"], hours=48)
    tick(clan)
    assert len(drafts(owner, clan["cid"], grant_id=gid)) == 1


def test_fee_estimates_answered_with_a_cached_copy_are_used():
    from clans.chain_watcher import EsploraChain

    class Client:
        def __init__(self, status):
            self.status = status

        def get_fee_estimates(self):
            body = '{"1": 3.2, "6": 1.4, "144": 0.1}'
            raise bdk.EsploraError.HttpResponse(status=self.status, error_message=body)

    chain = EsploraChain.__new__(EsploraChain)
    chain.client = Client(203)
    # The 6-block estimate, kept to a thousandth rather than rounded up to 2.
    assert chain.fee_rate() == 1.4
    chain.client = Client(429)
    with pytest.raises(bdk.EsploraError.HttpResponse):
        chain.fee_rate()


def test_the_laptop_registers_wallets_from_the_server_after_a_phone_check(
    clan, tmp_path, monkeypatch
):
    from clans import oversight

    home = tmp_path / "laptop"
    words = str(bdk.Mnemonic.from_entropy(bytes([1]) * 16))
    oversight.create_key(home, "correct horse battery staple", words)
    settings = clan["app"].state.security.settings
    settings.clan_wallet_oversight_token_hashes = oversight.connect(home, ORIGIN)
    token = json.loads((home / oversight.SERVER_FILE).read_text(encoding="utf-8"))["token"]
    laptop = TestClient(clan["app"], base_url=ORIGIN, headers={"Authorization": "Bearer " + token})
    assert TestClient(clan["app"], base_url=ORIGIN).get("/api/oversight/wallets").status_code == 401
    (listed,) = laptop.get("/api/oversight/wallets").json()
    assert listed["clan_name"] == "Real Treasury" and listed["generation"] == 1
    monkeypatch.setattr(oversight, "server", lambda _: laptop)

    # A code that doesn't match the phone registers nothing.
    monkeypatch.setattr("builtins.input", lambda _: "qqqqqqqq")
    assert oversight.main(["--home", str(home), "add-wallet"]) == 2
    assert clan["cid"] not in oversight.load_register(home)["wallets"]

    monkeypatch.setattr("builtins.input", lambda _: clan["policy"].wallet_code())
    assert oversight.main(["--home", str(home), "add-wallet"]) == 0
    saved = oversight.load_register(home)["wallets"][clan["cid"]]
    assert saved["generation"] == 1 and saved["wallet_code"] == clan["policy"].wallet_code()
    # Already registered: nothing is asked again.
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("asked again"))
    assert oversight.main(["--home", str(home), "add-wallet"]) == 0


def test_fees_follow_the_exact_rate_and_the_coins_spent(clan):
    """The mainnet trial paid 2 sat/vB for a 1.01 estimate, and the preview counted one coin."""
    owner, cid, chain = clan["signers"][0], clan["cid"], clan["chain"]
    chain.rate = 1.011
    fund_clan(clan, 25_000)
    fund_clan(clan, 25_000)
    gid = accepted_grant(clan)
    quote = owner.get(f"/api/clans/{cid}/grants/{gid}/payout-quote?address={DESTINATION}")
    assert quote.status_code == 200, quote.text
    quote = quote.json()
    # 1.011 is kept as 1.012 (BDK's unit rounds up), not 2.
    assert quote["fee_rate_sat_vb"] == 1.012
    # Two coins of 25,000 sats are needed for 40,000: 226 vB plus 142 for the second coin.
    assert quote["estimated_fee_sats"] == math.ceil(1.012 * (226 + 142))
    route = f"/api/clans/{cid}/grants/{gid}/payout-address"
    assert owner.post(route, json={"address": DESTINATION}).status_code == 200
    tick(clan)
    (payout,) = drafts(owner, cid, grant_id=gid)
    assert coins_spent(payout) == 2
    assert abs(payout["fee_sats"] - quote["estimated_fee_sats"]) <= 3
    assert payout["fee_rate_sat_vb"] == 1.012
    (received,) = payout["recipients"]
    assert abs(received["received_sats"] - quote["estimated_received_sats"]) <= 3


def test_one_large_coin_is_spent_before_many_small_ones(clan):
    owner, cid = clan["signers"][0], clan["cid"]
    for amount in (5_000, 5_000, 60_000):
        fund_clan(clan, amount)
    gid = accepted_grant(clan)
    route = f"/api/clans/{cid}/grants/{gid}/payout-address"
    assert owner.post(route, json={"address": DESTINATION}).status_code == 200
    tick(clan)
    (payout,) = drafts(owner, cid, grant_id=gid)
    assert coins_spent(payout) == 1


def coins_spent(payout):
    return len(bdk.Psbt(payout["psbt"]).extract_tx_unchecked_fee_rate().input())
