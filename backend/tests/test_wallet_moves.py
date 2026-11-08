"""Moving a clan to a new wallet generation, and refreshing the recovery wait.

A new generation is set up exactly like the first wallet while the old one keeps working.
Once it's active, the chain watcher moves the old wallet's coins across in one payment,
signed like any payout. A refresh is the same payment back to the wallet's own change
address, built before any coin's recovery wait nears its end.
"""

import bdkpython as bdk
import pytest
import test_clan_wallet_payments as payments
from clan_wallet_helpers import DESTINATION, secret_key, sign_normal_path
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_clan_wallet_api import phone_code
from test_clan_wallet_payments import (
    GRANT_SATS,
    accepted_grant,
    address,
    balance_msat,
    drafts,
    fund_clan,
    tick,
)
from test_live_app import ORIGIN

from clans import oversight
from clans.clan_wallet import ClanPolicy, ClanWallet
from clans.money_models import LedgerEntry
from clans.wallet_models import ClanWalletRecord, WalletAlarm, WalletPayout, WalletReceipt

PASSPHRASE = "correct horse battery staple"
# Shared fixtures: an active 3-signatory clan wallet and its test keys.
clan, keys = payments.clan, payments.keys


def policy_of(view) -> ClanPolicy:
    policy = view["policy"]
    return ClanPolicy.create(
        network=policy["network"],
        oversight=policy["oversight"],
        signers=policy["signers"],
        recovery_threshold=policy["recovery_threshold"],
        recovery_blocks=policy["recovery_blocks"],
    )


def sign_with(clan, client, seed, policy, payout):
    """A signatory's phone signs with the saved copy of the payout's wallet generation."""
    signed = sign_normal_path(policy, secret_key(seed), payout["psbt"])
    route = f"/api/clans/{clan['cid']}/wallet/payouts/{payout['id']}/signature"
    return client.post(route, json={"psbt": signed})


def oversight_with(clan, policy, payout):
    signed = sign_normal_path(policy, secret_key(1), payout["psbt"])
    tool = TestClient(clan["app"], base_url=ORIGIN)
    route = f"/api/clans/{clan['cid']}/wallet/payouts/{payout['id']}/oversight-signature"
    return tool.post(route, json={"psbt": signed})


def new_wallet(clan, keys, reason="stolen_phone"):
    """The third signatory's phone was stolen: they make a new key, the others keep theirs."""
    owner, second, third = clan["signers"]
    route = f"/api/clans/{clan['cid']}/wallet"
    response = third.post(route + "/next", json={"reason": reason})
    assert response.status_code == 200, response.text
    for client, key in ((owner, keys[1]), (second, keys[2]), (third, keys[4])):
        assert client.post(route + "/keys", json={"key": key}).status_code == 200
    upcoming = owner.get(route).json()["next"]
    assert upcoming["status"] == "confirming"
    for client in (owner, second, third):
        response = client.post(route + "/confirm", json={"wallet_code": phone_code(upcoming)})
        assert response.status_code == 200, response.text
    view = owner.get(route).json()
    assert view["generation"] == 2 and view["status"] == "active" and view["next"] is None
    return view, policy_of(view)


def finish(clan, payout, signers):
    """Two signatories and Afribit sign; the watcher sends it; it gets 3 confirmations."""
    for client, seed, policy in signers:
        assert sign_with(clan, client, seed, policy, payout).status_code == 200
    assert oversight_with(clan, signers[0][2], payout).status_code == 200
    tick(clan)
    chain = clan["chain"]
    assert chain.broadcasts[-1] == payout["txid"]
    chain.mine(payout["txid"])
    tick(clan)


def test_starting_a_new_wallet_keeps_the_current_one_working(clan, keys):
    owner, second, third = clan["signers"]
    cid, route = clan["cid"], f"/api/clans/{clan['cid']}/wallet"
    before = address(owner, cid, "grant_funding")
    reason = {"reason": "stolen_phone"}
    assert clan["member"].post(route + "/next", json=reason).status_code == 403
    assert third.post(route + "/next", json={"reason": "because"}).status_code == 422
    view = third.post(route + "/next", json=reason).json()
    assert view["status"] == "active" and view["generation"] == 1
    assert view["next"]["status"] == "collecting_keys" and view["next"]["generation"] == 2
    assert view["next"]["started_by"] == "Third Signer"
    assert view["next"]["start_reason"] == "stolen_phone"
    assert owner.post(route + "/next", json=reason).status_code == 409
    # Money still goes to the current wallet while the new one is set up.
    assert address(owner, cid, "grant_funding") == before
    # Keys now go to the new wallet. The same keys as before make the same wallet: refused.
    for client, key in ((owner, keys[1]), (second, keys[2])):
        assert client.post(route + "/keys", json={"key": key}).status_code == 200
    response = third.post(route + "/keys", json={"key": keys[3]})
    assert response.status_code == 409 and "same wallet" in response.json()["detail"]
    # Stopping it changes nothing; it can be started again later.
    response = second.post(route + "/next/cancel", json={})
    assert response.status_code == 200, response.text
    view = response.json()
    assert view["next"] is None and view["generation"] == 1 and view["earlier"] == []
    assert clan["member"].post(route + "/next/cancel", json={}).status_code == 403
    assert second.post(route + "/next/cancel", json={}).status_code == 409
    response = owner.post(route + "/keys", json={"key": keys[4]})
    assert response.status_code == 409 and "start a new clan wallet" in response.json()["detail"]
    again = owner.post(route + "/next", json={"reason": "other"}).json()
    assert again["next"]["generation"] == 3


def test_the_old_wallet_is_moved_into_the_new_one(clan, keys):
    owner, second, third = clan["signers"]
    cid, old = clan["cid"], clan["policy"]
    fund_clan(clan, 100_000)
    old_address = address(owner, cid, "contribution")["address"]
    view, new = new_wallet(clan, keys)
    assert view["earlier"][0]["generation"] == 1
    # New money goes to the new wallet.
    assert address(owner, cid, "grant_funding")["address"] == ClanWallet(new).address(0)
    tick(clan)
    (move,) = drafts(owner, cid)
    assert move["kind"] == "move" and move["generation"] == 1 and move["recipients"] == []
    assert move["destination"] == {
        "generation": 2,
        "keychain": "internal",
        "index": 0,
        "address": ClanWallet(new).change_address(0),
    }
    # What a phone checks before signing: one output, to the new wallet it confirmed.
    amount = ClanWallet(old).check_sweep(
        move["psbt"], ClanWallet(new).change_address(0), max_fee_sats=move["max_fee_sats"]
    )
    assert amount == 100_000 - move["fee_sats"]
    # The old wallet's keys sign the move. The phone that was stolen isn't needed.
    finish(clan, move, [(owner, 2, old), (second, 3, old)])
    (move,) = drafts(owner, cid)
    assert move["status"] == "confirmed"
    # The clan pays only the fee. The moved coins aren't counted again as a deposit.
    assert balance_msat(clan) == ((100_000 - move["fee_sats"]) * 1000, 0)
    with clan["app"].state.security.db() as db:
        old_record, new_record = db.scalars(
            select(ClanWalletRecord).order_by(ClanWalletRecord.generation)
        ).all()
        assert (old_record.status, old_record.balance_sats) == ("retired", 0)
        assert (
            db.scalar(select(WalletReceipt).where(WalletReceipt.wallet_id == new_record.id)) is None
        )
        fee = db.scalar(select(LedgerEntry).where(LedgerEntry.event == "network_fee"))
        assert fee.amount_msat == move["fee_sats"] * 1000
    tick(clan)
    with clan["app"].state.security.db() as db:
        assert db.get(ClanWalletRecord, new_record.id).balance_sats == amount

    # A grant is paid from the new wallet, signed with the new keys.
    gid = accepted_grant(clan)
    route = f"/api/clans/{cid}/grants/{gid}/payout-address"
    assert owner.post(route, json={"address": DESTINATION}).status_code == 200
    tick(clan)
    (payout,) = drafts(owner, cid, grant_id=gid)
    assert payout["kind"] == "grant" and payout["generation"] == 2
    assert sign_with(clan, owner, 2, new, payout).status_code == 403  # the beneficiary
    finish(clan, payout, [(second, 3, new), (third, 5, new)])
    assert drafts(owner, cid, grant_id=gid)[0]["status"] == "confirmed"

    # A late payment to an old address is still credited, then moved across too.
    late = clan["chain"].pay(old_address, 20_000)
    clan["chain"].mine(late)
    tick(clan)
    moves = drafts(owner, cid, status="awaiting_signatures")
    assert [item["kind"] for item in moves] == ["move"]
    assert moves[0]["destination"]["index"] > 0  # a fresh address, not the first move's


def test_a_grant_from_the_old_wallet_is_paid_before_the_move(clan, keys):
    owner, second, third = clan["signers"]
    cid, old = clan["cid"], clan["policy"]
    fund_clan(clan, 100_000)
    gid = accepted_grant(clan)
    route = f"/api/clans/{cid}/grants/{gid}/payout-address"
    assert owner.post(route, json={"address": DESTINATION}).status_code == 200
    tick(clan)
    (payout,) = drafts(owner, cid, grant_id=gid)
    _, new = new_wallet(clan, keys)
    tick(clan)
    assert [item["kind"] for item in drafts(owner, cid)] == ["grant"]
    # It's still signed with the old wallet's keys, then the change moves across.
    finish(clan, payout, [(second, 3, old), (third, 4, old)])
    move = drafts(owner, cid, status="awaiting_signatures")[0]
    assert move["kind"] == "move"
    paid = drafts(owner, cid, grant_id=gid)[0]
    change = 100_000 - GRANT_SATS
    assert (
        ClanWallet(old).check_sweep(
            move["psbt"], ClanWallet(new).change_address(0), max_fee_sats=move["max_fee_sats"]
        )
        == change - move["fee_sats"]
    )
    assert paid["status"] == "confirmed"


def test_a_grant_waiting_on_the_old_wallet_is_paid_from_the_new_one(clan, keys):
    owner, second, third = clan["signers"]
    cid = clan["cid"]
    fund_clan(clan, 100_000)
    gid = accepted_grant(clan)
    route = f"/api/clans/{cid}/grants/{gid}/payout-address"
    # The address is given, but the watcher hasn't built the payout when the new wallet starts.
    assert owner.post(route, json={"address": DESTINATION}).status_code == 200
    _, new = new_wallet(clan, keys)
    tick(clan)
    assert [item["kind"] for item in drafts(owner, cid)] == ["move"]
    move = drafts(owner, cid)[0]
    finish(clan, move, [(owner, 2, clan["policy"]), (second, 3, clan["policy"])])
    tick(clan)
    (payout,) = drafts(owner, cid, grant_id=gid)
    assert payout["generation"] == 2


def test_coins_are_refreshed_before_the_recovery_wait_ends(clan):
    owner, second, third = clan["signers"]
    cid, chain, policy = clan["cid"], clan["chain"], clan["policy"]
    fund_clan(clan, 100_000)
    blocks = policy.recovery_blocks
    due = blocks - blocks // 6
    # The coin has 3 confirmations now. Wait until one block before the refresh is due.
    chain.tip += due - 4
    tick(clan)
    assert drafts(owner, cid) == []
    chain.tip += 1
    tick(clan)
    (refresh,) = drafts(owner, cid)
    assert refresh["kind"] == "refresh" and refresh["generation"] == 1
    assert refresh["destination"] == {
        "generation": 1,
        "keychain": "internal",
        "index": 0,
        "address": ClanWallet(policy).change_address(0),
    }
    assert refresh["fee_paid_by"] == "clan"
    finish(clan, refresh, [(second, 3, policy), (third, 4, policy)])
    assert drafts(owner, cid)[0]["status"] == "confirmed"
    assert balance_msat(clan) == ((100_000 - refresh["fee_sats"]) * 1000, 0)
    # The refreshed coin starts a new wait. No other refresh for now.
    chain.tip += 10
    tick(clan)
    assert len(drafts(owner, cid)) == 1
    # A grant spends the refreshed coin normally.
    gid = accepted_grant(clan)
    route = f"/api/clans/{cid}/grants/{gid}/payout-address"
    assert owner.post(route, json={"address": DESTINATION}).status_code == 200
    tick(clan)
    (payout,) = drafts(owner, cid, grant_id=gid)
    finish(clan, payout, [(second, 3, policy), (third, 4, policy)])
    assert drafts(owner, cid, grant_id=gid)[0]["status"] == "confirmed"


def test_a_grant_can_use_coins_of_a_refresh_nobody_signed(clan):
    owner = clan["signers"][0]
    cid, chain, policy = clan["cid"], clan["chain"], clan["policy"]
    fund_clan(clan, 100_000)
    chain.tip += policy.recovery_blocks
    tick(clan)
    (refresh,) = drafts(owner, cid)
    assert refresh["kind"] == "refresh"
    with clan["app"].state.security.db() as db:
        # Past the full wait, the signatories could spend without Afribit. Everyone hears.
        assert db.scalar(select(WalletAlarm).where(WalletAlarm.kind == "recovery_path_open"))
    gid = accepted_grant(clan)
    route = f"/api/clans/{cid}/grants/{gid}/payout-address"
    assert owner.post(route, json={"address": DESTINATION}).status_code == 200
    tick(clan)
    statuses = {item["kind"]: item["status"] for item in drafts(owner, cid)}
    assert statuses == {"refresh": "expired", "grant": "awaiting_signatures"}


def test_a_stuck_move_gets_a_higher_fee_version(clan, keys):
    owner, second, _ = clan["signers"]
    cid, chain, old = clan["cid"], clan["chain"], clan["policy"]
    fund_clan(clan, 100_000)
    new_wallet(clan, keys)
    tick(clan)
    (move,) = drafts(owner, cid)
    for client, seed in ((owner, 2), (second, 3)):
        assert sign_with(clan, client, seed, old, move).status_code == 200
    assert oversight_with(clan, old, move).status_code == 200
    tick(clan)
    with clan["grants"].paused(), clan["app"].state.security.db() as db:
        row = db.get(WalletPayout, move["id"])
        row.broadcast_at = "2000-01-01T00:00:00+00:00"
    chain.rate = 6
    tick(clan)
    bumped = drafts(owner, cid, status="awaiting_signatures")[0]
    assert bumped["kind"] == "move" and bumped["replaces"] == move["id"]
    assert bumped["destination"] == move["destination"]
    assert bumped["fee_sats"] > move["fee_sats"]


@pytest.fixture
def laptop(tmp_path):
    home = tmp_path / "laptop"
    oversight.create_key(home, PASSPHRASE, str(bdk.Mnemonic.from_entropy(bytes([1]) * 16)))
    return home


def test_the_oversight_laptop_checks_a_move_against_its_own_records(clan, keys, laptop):
    owner = clan["signers"][0]
    cid, old = clan["cid"], clan["policy"]
    fund_clan(clan, 100_000)
    first = owner.get(f"/api/clans/{cid}/wallet").json()
    oversight.add_wallet(laptop, cid, first, phone_code(first))
    view, new = new_wallet(clan, keys)
    tick(clan)
    (move,) = drafts(owner, cid)
    with pytest.raises(oversight.OversightError, match="Register the clan's new wallet"):
        oversight.review(laptop, move)
    oversight.add_wallet(laptop, cid, view, phone_code(view))
    checked = oversight.review(laptop, move)
    assert checked.kind == "move" and checked.destination == ClanWallet(new).change_address(0)
    assert checked.total_sats == 100_000 - move["fee_sats"]
    # A server claiming a different index or address is refused.
    with pytest.raises(oversight.OversightError, match="doesn't match"):
        oversight.review(laptop, move | {"destination": move["destination"] | {"index": 1}})
    with pytest.raises(oversight.OversightError, match="own wallet"):
        oversight.review(laptop, move | {"destination": move["destination"] | {"generation": 1}})
    # Beyond the first 1,000 change addresses, which recovery checks, is refused too.
    with pytest.raises(oversight.OversightError, match="Invalid change address index"):
        oversight.review(laptop, move | {"destination": move["destination"] | {"index": 1000}})
    assert ClanWallet(new).change_address(999)
    signed, complete = oversight.sign(laptop, move, PASSPHRASE)
    assert not complete
    oversight.sign(laptop, move, PASSPHRASE)
    register = oversight.load_register(laptop)
    assert [item["kind"] for item in register["payouts"]] == ["move"]
    assert register["wallets"][cid]["earlier"][0]["generation"] == 1
    # The backup is for the newest wallet.
    assert oversight.wallet_backup(laptop, cid)["generation"] == 2
    assert old != new
