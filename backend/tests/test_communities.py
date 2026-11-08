"""Communities: each one's clans get its own oversight, and each laptop sees only its own."""

import json
import secrets

import bdkpython as bdk
import pytest
import test_clan_wallet_payments as payments
from clan_wallet_helpers import DESTINATION, secret_key
from fastapi.testclient import TestClient
from role_grants import GrantChecker
from test_clan_wallet_api import make_app, phone_code
from test_clan_wallet_payments import FakeChain, accepted_grant, drafts, fund_clan, sign, tick
from test_live_app import ORIGIN, join, signup

from clans import communities
from clans import oversight as ov
from clans.chain_watcher import ChainWatcher
from clans.clan_wallet import ClanPolicy
from clans.communities import CommunityError
from clans.live_security import Security

keys = payments.keys
PASSPHRASE = "correct horse battery staple"


def operator(app):
    """The platform operator's own connection: the only one that changes communities."""
    return Security(app.state.security.settings)


def laptop_home(tmp_path, seed, name):
    home = tmp_path / name
    ov.create_key(home, PASSPHRASE, str(bdk.Mnemonic.from_entropy(bytes([seed]) * 16)))
    return home, ov.connect(home, ORIGIN)


def laptop(app, home):
    token = json.loads((home / ov.SERVER_FILE).read_text(encoding="utf-8"))["token"]
    return TestClient(app, base_url=ORIGIN, headers={"Authorization": "Bearer " + token})


def new_clan(owner, code=None, name="Kibera Savers Clan"):
    body = {
        "name": name,
        "description": "Our purpose",
        "target_signers": 3,
        "member_vote_quorum": 2,
        "be_signer": True,
        "accepted_custody": True,
    }
    if code is not None:
        body["community_code"] = code
    return owner.post("/api/clans", json=body, headers={"Idempotency-Key": secrets.token_hex(16)})


def activate(app, cid, signers, seeds):
    route = f"/api/clans/{cid}/wallet"
    for client, seed in zip(signers, seeds, strict=True):
        key = str(secret_key(seed).as_public())
        response = client.post(route + "/keys", json={"key": key})
        assert response.status_code == 200, response.text
    view = signers[0].get(route).json()
    for client in signers:
        assert client.post(route + "/confirm", json={"wallet_code": phone_code(view)}).is_success
    view = signers[0].get(route).json()
    assert view["status"] == "active"
    return view


@pytest.fixture
def world(tmp_path, keys):
    """Afribit (the default community, from the settings) and a second community, Kibera
    Savers, with one clan each. Each community has its own oversight laptop."""
    app = make_app(tmp_path, keys)
    grants = GrantChecker()
    grants.watch(app.state.security.engine, "web")
    afribit_home, afribit_hash = laptop_home(tmp_path, 1, "afribit-laptop")  # seed 1 = keys[0]
    app.state.security.settings.clan_wallet_oversight_token_hashes = afribit_hash
    kibera_home, kibera_hash = laptop_home(tmp_path, 5, "kibera-laptop")
    admin = operator(app)
    with admin.db() as db:
        _, code = communities.create(db, "Kibera Savers")
        communities.add_laptop(
            db,
            app.state.security.settings,
            "kibera-savers",
            ov.public_key(kibera_home),
            kibera_hash,
        )

    def people(prefix):
        return [signup(app, f"{prefix} {n}")[0] for n in ("Organizer", "Second", "Third")]

    afribit_signers = people("Afribit")
    afribit_cid = new_clan(afribit_signers[0], name="Afribit Clan").json()["clan_id"]
    kibera_signers = people("Kibera")
    response = new_clan(kibera_signers[0], code.lower().replace("-", " "))
    assert response.status_code == 200, response.text
    kibera_cid = response.json()["clan_id"]
    for signers, cid in ((afribit_signers, afribit_cid), (kibera_signers, kibera_cid)):
        for member in signers[1:]:
            join(signers[0], member, cid)
    chain = FakeChain()
    watcher = ChainWatcher(app.state.security.settings, chain=chain)
    grants.watch(watcher.security.engine, "worker")
    yield {
        "app": app,
        "code": code,
        "chain": chain,
        "watcher": watcher,
        "afribit": (afribit_cid, afribit_signers, afribit_home),
        "kibera": (kibera_cid, kibera_signers, kibera_home),
    }
    grants.assert_clean()
    for engine in (watcher.security.engine, admin.engine, app.state.security.engine):
        engine.dispose()


def as_clan(world, which, view, seeds):
    """The shape test_clan_wallet_payments' helpers take."""
    cid, signers, _ = world[which]
    policy = ClanPolicy.create(
        network="signet", oversight=view["policy"]["oversight"], signers=view["policy"]["signers"]
    )
    secrets_by_client = {id(c): secret_key(s) for c, s in zip(signers, seeds, strict=True)}
    return {
        "app": world["app"],
        "cid": cid,
        "signers": signers,
        "policy": policy,
        "chain": world["chain"],
        "watcher": world["watcher"],
        "secret": lambda c: secrets_by_client[id(c)],
    }


def test_members_see_which_community_oversees_their_clan(world):
    afribit_cid, afribit_signers, _ = world["afribit"]
    kibera_cid, kibera_signers, _ = world["kibera"]
    assert afribit_signers[0].get(f"/api/clans/{afribit_cid}").json()["community"] == {
        "id": None,
        "name": "Afribit",
    }
    assert kibera_signers[0].get(f"/api/clans/{kibera_cid}").json()["community"] == {
        "id": "kibera-savers",
        "name": "Kibera Savers",
    }
    stranger = signup(world["app"], "Stranger")[0]
    response = new_clan(stranger, "ABCD-EFGH")
    assert response.status_code == 400
    assert "community code isn't valid" in response.json()["detail"]


def test_a_clan_wallet_takes_its_own_communitys_oversight_key(world):
    afribit_cid, afribit_signers, afribit_home = world["afribit"]
    kibera_cid, kibera_signers, kibera_home = world["kibera"]
    before = kibera_signers[0].get(f"/api/clans/{kibera_cid}/wallet").json()
    assert before["oversight_keys"] == [ov.public_key(kibera_home)]
    # The other community's oversight key can't be a signatory key here either.
    refused = kibera_signers[0].post(
        f"/api/clans/{kibera_cid}/wallet/keys", json={"key": ov.public_key(kibera_home)}
    )
    assert refused.status_code == 400
    kibera = activate(world["app"], kibera_cid, kibera_signers, (2, 3, 4))
    afribit = activate(world["app"], afribit_cid, afribit_signers, (2, 3, 4))
    assert kibera["policy"]["oversight"] == [ov.public_key(kibera_home)]
    assert afribit["policy"]["oversight"] == [ov.public_key(afribit_home)]
    assert kibera["wallet_code"] != afribit["wallet_code"]


def test_a_community_without_a_laptop_cant_make_wallets(world):
    admin = operator(world["app"])
    with admin.db() as db:
        _, code = communities.create(db, "Mathare Group")
    admin.engine.dispose()
    owner = signup(world["app"], "Mathare Organizer")[0]
    cid = new_clan(owner, code).json()["clan_id"]
    response = owner.post(
        f"/api/clans/{cid}/wallet/keys", json={"key": str(secret_key(2).as_public())}
    )
    assert response.status_code == 409
    assert "Mathare Group hasn't set up an oversight laptop" in response.json()["detail"]


def test_each_laptop_sees_and_approves_only_its_own_communitys_payouts(world):
    app = world["app"]
    kibera_cid, kibera_signers, kibera_home = world["kibera"]
    afribit_cid, afribit_signers, afribit_home = world["afribit"]
    kibera_view = activate(app, kibera_cid, kibera_signers, (2, 3, 4))
    activate(app, afribit_cid, afribit_signers, (2, 3, 4))
    clan = as_clan(world, "kibera", kibera_view, (2, 3, 4))
    fund_clan(clan, 100_000)
    gid = accepted_grant(clan)
    owner, second, third = kibera_signers
    response = owner.post(
        f"/api/clans/{kibera_cid}/grants/{gid}/payout-address", json={"address": DESTINATION}
    )
    assert response.status_code == 200, response.text
    tick(clan)
    (payout,) = drafts(owner, kibera_cid, grant_id=gid)
    sign(clan, third, sign(clan, second, payout).json())

    afribit_laptop, kibera_laptop = laptop(app, afribit_home), laptop(app, kibera_home)
    assert afribit_laptop.get("/api/oversight/community").json()["name"] == "Afribit"
    assert kibera_laptop.get("/api/oversight/community").json()["name"] == "Kibera Savers"
    # Afribit's laptop doesn't see the Kibera clan at all.
    assert ov.pending(afribit_laptop) == []
    assert [w["clan_id"] for w in ov.wallets(afribit_laptop)] == [afribit_cid]
    # Kibera's laptop sees only its own clan, and can approve it.
    assert [w["clan_id"] for w in ov.wallets(kibera_laptop)] == [kibera_cid]
    (waiting,) = ov.pending(kibera_laptop)
    assert waiting["clan_name"] == "Kibera Savers Clan"
    (wallet,) = ov.unregistered(kibera_home, kibera_laptop)
    ov.add_wallet(kibera_home, kibera_cid, wallet, clan["policy"].wallet_code())
    start, end = ov.check_characters(DESTINATION)
    ov.confirm_address(kibera_home, DESTINATION, "Beneficiary", start, end, "signet")
    signed, _ = ov.sign(kibera_home, waiting, PASSPHRASE)
    ov.upload(kibera_laptop, ov.signed_file(waiting, ov.review(kibera_home, waiting), signed))
    tick(clan)
    assert world["chain"].broadcasts == [payout["txid"]]
    # Afribit's key couldn't have approved it: the wallet doesn't include it.
    with pytest.raises(ov.OversightError):
        ov.add_wallet(afribit_home, kibera_cid, wallet, clan["policy"].wallet_code())


def test_alarms_stay_within_the_community(world):
    app = world["app"]
    kibera_cid, kibera_signers, kibera_home = world["kibera"]
    afribit_cid, afribit_signers, afribit_home = world["afribit"]
    activate(app, kibera_cid, kibera_signers, (2, 3, 4))
    route = f"/api/clans/{afribit_cid}/wallet"
    for client, seed in zip(afribit_signers, (2, 3, 4), strict=True):
        client.post(route + "/keys", json={"key": str(secret_key(seed).as_public())})
    # A wrong wallet code on the Afribit clan is an alarm for Afribit only.
    afribit_signers[0].post(route + "/confirm", json={"wallet_code": "zzzzzzzz"})
    kinds = [a["kind"] for a in ov.alarms(laptop(app, afribit_home))]
    assert "wallet_code_mismatch" in kinds
    assert ov.alarms(laptop(app, kibera_home)) == []


def test_the_operator_command_keeps_each_key_and_laptop_in_one_community(world, tmp_path, keys):
    app = world["app"]
    settings = app.state.security.settings
    _, _, kibera_home = world["kibera"]
    other_home, other_hash = laptop_home(tmp_path, 7, "other-laptop")
    admin = operator(app)
    with admin.db() as db:
        with pytest.raises(CommunityError, match="already belongs to Afribit"):
            communities.add_laptop(db, settings, "kibera-savers", keys[0], other_hash)
        kibera_hash = db.get(communities.Community, "kibera-savers").token_hashes[0]
        with pytest.raises(CommunityError, match="already belongs to Kibera Savers"):
            communities.add_laptop(
                db, settings, "kibera-savers", ov.public_key(other_home), kibera_hash
            )
        with pytest.raises(CommunityError, match="already exists"):
            communities.create(db, "kibera savers!")
        # A new join code replaces the old one.
        code = communities.rotate_code(db, "kibera-savers")
    owner = signup(app, "Late Organizer")[0]
    assert new_clan(owner, world["code"]).status_code == 400
    assert new_clan(owner, code).status_code == 200
    with admin.db() as db:
        # Closing a community stops new clans. Its laptop keeps working.
        db.get(communities.Community, "kibera-savers").active = False
    assert new_clan(signup(app, "Later Organizer")[0], code).status_code == 400
    assert laptop(app, kibera_home).get("/api/oversight/community").status_code == 200
    admin.engine.dispose()


def test_a_laptop_key_in_use_is_removed_only_with_force(world):
    app = world["app"]
    kibera_cid, kibera_signers, kibera_home = world["kibera"]
    activate(app, kibera_cid, kibera_signers, (2, 3, 4))
    admin = operator(app)
    with admin.db() as db:
        with pytest.raises(CommunityError, match="Clan wallets already use this key"):
            communities.remove_laptop(db, "kibera-savers", key=ov.public_key(kibera_home))
        row = communities.remove_laptop(
            db, "kibera-savers", key=ov.public_key(kibera_home), force=True
        )
        assert row.oversight_keys == []
    admin.engine.dispose()


def test_the_operator_command_line(world, monkeypatch, capsys):
    settings = world["app"].state.security.settings
    for name, value in {
        "DATABASE_URL": settings.database_url.get_secret_value(),
        "ENVIRONMENT": "test",
        "SESSION_SECRET": "a" * 64,
        "PUBLIC_ORIGIN": ORIGIN,
        "RP_ID": "localhost",
    }.items():
        monkeypatch.setenv("CLANS_" + name, value)
    assert communities.main(["create", "--name", "Mathare Group"]) == 0
    out = capsys.readouterr().out
    assert "Join code:" in out
    assert communities.main(["list"]) == 0
    listed = capsys.readouterr().out
    assert "Afribit (default)" in listed and "Kibera Savers (kibera-savers)" in listed
    assert communities.main(["new-code", "nobody"]) == 1
