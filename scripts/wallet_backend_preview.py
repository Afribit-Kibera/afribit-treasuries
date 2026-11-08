"""Loopback-only F8 check: real app/SQLite/watcher, with only the Bitcoin network simulated.

Run with the isolated test environment. It never reads production secrets or contacts a node.
Vite: CLANS_DEV_API_TARGET=http://127.0.0.1:8418, port 5183.
"""

import json
import secrets
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/src"))
sys.path.insert(0, str(ROOT / "backend/tests"))
import httpx
import test_live_app
import uvicorn
from clan_wallet_helpers import secret_key, sign_normal_path
from clans.chain_watcher import ChainWatcher
from clans.clan_wallet import ClanPolicy
from clans.db import Base
from clans.display_rates import DisplayRates
from clans.live_app import create_app
from clans.live_config import LiveSettings
from clans.wallet_models import ChainStatus
from fastapi import HTTPException, Request
from sqlalchemy import select
from test_clan_wallet_api import phone_code, three_signer_clan
from test_clan_wallet_payments import (
    FakeChain,
    accepted_grant,
    fund_clan,
    make_stuck,
    oversight_sign,
    sign,
    tick,
)

ORIGIN = "http://localhost:5183"
test_live_app.ORIGIN = ORIGIN
test_live_app.Authenticator.client_data.__defaults__ = (ORIGIN,)
test_live_app.Authenticator.registration.__kwdefaults__["origin"] = ORIGIN
settings = LiveSettings(
    environment="test",
    database_url="sqlite:///"
    + (ROOT / (".local/wallet-f8-" + secrets.token_hex(5) + ".db")).as_posix(),
    session_secret=secrets.token_urlsafe(64),
    public_origin=ORIGIN,
    rp_id="localhost",
    static_directory=None,
    clan_wallets_enabled=True,
    clan_wallet_network="signet",
    clan_wallet_oversight_keys=str(secret_key(1).as_public()),
    receiving_enabled=True,
    payouts_enabled=True,
    btcpay_api_key="local-test-only",
    btcpay_store_id="local-test-only",
    expected_node_pubkey="02" + "11" * 32,
)
app = create_app(settings)
Base.metadata.create_all(app.state.security.engine)
app.state.security.display_rates = DisplayRates(
    transport=httpx.MockTransport(
        lambda req: httpx.Response(
            200,
            json={"bitcoin": {"kes": 10000000, "last_updated_at": int(time.time())}},
        )
    )
)
cid, signers, member = three_signer_clan(app)
for client, seed in zip(signers, (2, 3, 4)):
    response = client.post(
        f"/api/clans/{cid}/wallet/keys", json={"key": str(secret_key(seed).as_public())}
    )
    assert response.is_success
view = signers[0].get(f"/api/clans/{cid}/wallet").json()
for client in signers:
    assert client.post(
        f"/api/clans/{cid}/wallet/confirm", json={"wallet_code": phone_code(view)}
    ).is_success
policy = ClanPolicy.create(
    network="signet",
    oversight=view["policy"]["oversight"],
    signers=view["policy"]["signers"],
)
chain = FakeChain()
watcher = ChainWatcher(settings, chain=chain)
key_by_client = {id(c): secret_key(seed) for c, seed in zip(signers, (2, 3, 4))}
state = {
    "app": app,
    "cid": cid,
    "signers": signers,
    "member": member,
    "policy": policy,
    "chain": chain,
    "watcher": watcher,
    "secret": lambda c: key_by_client[id(c)],
}
fund_clan(state, 200000)
gid = accepted_grant(state)
gate = secrets.token_urlsafe(32)
sessions = {
    role: client.cookies.get(settings.cookie_name)
    for role, client in zip(
        ("beneficiary", "signer", "third", "member"), [*signers, member]
    )
}
(ROOT / ".local/wallet-f8-session.json").write_text(
    json.dumps(
        {
            "gate": gate,
            "sessions": sessions,
            "cookie_name": settings.cookie_name,
            "clan_id": cid,
            "grant_id": gid,
            "origin": ORIGIN,
        }
    ),
    encoding="utf-8",
)


def control(request):
    if request.client.host not in {"127.0.0.1", "::1"} or not secrets.compare_digest(
        request.headers.get("X-Local-Wallet-Check", ""), gate
    ):
        raise HTTPException(404)


@app.post("/__wallet_test/{action}")
async def change(action: str, request: Request):
    control(request)
    body = await request.json()
    if action == "pay":
        txid = chain.pay(body["address"], int(body["amount_sats"]))
        tick(state)
        return {"txid": txid}
    if action == "mine":
        chain.mine(body["txid"], int(body.get("blocks", 3)))
        tick(state)
        return {"ok": True}
    if action == "drop":
        chain.drop(body["txid"])
        tick(state)
        return {"ok": True}
    if action == "tick":
        tick(state)
        return {"ok": True}
    if action == "next-keys":
        route = f"/api/clans/{cid}/wallet"
        for client, seed in ((signers[1], 3), (signers[2], 5)):
            result = client.post(route + "/keys", json={"key": str(secret_key(seed).as_public())})
            assert result.is_success, result.text
        return {"ok": True}
    if action == "next-confirm":
        route = f"/api/clans/{cid}/wallet"
        upcoming = signers[1].get(route).json()["next"]
        for client in (signers[1], signers[2]):
            result = client.post(route + "/confirm", json={"wallet_code": phone_code(upcoming)})
            assert result.is_success, result.text
        tick(state)
        return {"ok": True}
    if action == "finish-wallet-payment":
        route = f"/api/clans/{cid}/wallet/payouts/{body['id']}"
        payout = signers[1].get(route).json()
        if payout["generation"] == 1:
            source_policy = policy
        else:
            source = signers[1].get(f"/api/clans/{cid}/wallet").json()["policy"]
            source_policy = ClanPolicy.create(**source)
        signed = sign_normal_path(source_policy, secret_key(3), payout["psbt"])
        response = signers[1].post(route + "/signature", json={"psbt": signed})
        assert response.is_success, response.text
        signed = sign_normal_path(source_policy, secret_key(1), payout["psbt"])
        response = signers[0].post(route + "/oversight-signature", json={"psbt": signed})
        assert response.is_success, response.text
        tick(state)
        chain.mine(payout["txid"])
        tick(state)
        return {"ok": True}
    if action == "age-coins":
        chain.tip += policy.recovery_blocks - policy.recovery_blocks // 6
        tick(state)
        return {"ok": True}
    if action == "bump":
        make_stuck(state, body["id"])
        chain.rate = 6
        tick(state)
        return {"ok": True}
    if action == "stale":
        with app.state.security.db() as db:
            row = db.scalar(select(ChainStatus))
            row.observed_at = "2000-01-01T00:00:00+00:00"
        return {"ok": True}
    if action == "co-sign":
        payout = signers[2].get(f"/api/clans/{cid}/wallet/payouts/{body['id']}").json()
        signed = sign(state, signers[2], payout)
        assert signed.is_success, signed.text
        approved = oversight_sign(state, payout)
        assert approved.is_success, approved.text
        return {"ok": True}
    if action == "third-sign":
        payout = signers[2].get(f"/api/clans/{cid}/wallet/payouts/{body['id']}").json()
        response = sign(state, signers[2], payout)
        assert response.is_success, response.text
        return {"ok": True}
    if action == "oversight":
        payout = signers[0].get(f"/api/clans/{cid}/wallet/payouts/{body['id']}").json()
        response = oversight_sign(state, payout)
        assert response.is_success, response.text
        return {"ok": True}
    if action == "broadcast-mine":
        tick(state)
        payout = signers[0].get(f"/api/clans/{cid}/wallet/payouts/{body['id']}").json()
        if body.get("confirm", False):
            if payout["replaces"]:
                original = (
                    signers[0]
                    .get(f"/api/clans/{cid}/wallet/payouts/{payout['replaces']}")
                    .json()
                )
                chain.drop(original["txid"])
            chain.mine(payout["txid"])
            tick(state)
        return {
            "status": signers[0]
            .get(f"/api/clans/{cid}/wallet/payouts/{body['id']}")
            .json()["status"]
        }
    raise HTTPException(404)


print(
    "Isolated wallet API ready on 127.0.0.1:8418; session details kept in .local.",
    flush=True,
)
uvicorn.run(app, host="127.0.0.1", port=8418, access_log=False)
