"""Clan wallet setup API: signatories register public keys and confirm the wallet code."""

import pytest
from clan_wallet_helpers import secret_key
from role_grants import GrantChecker
from sqlalchemy import select
from test_live_app import ORIGIN, clan, join, signup

from clans.clan_wallet import ClanPolicy
from clans.db import Base
from clans.live_app import create_app
from clans.live_config import LiveSettings
from clans.models import AuditEvent


@pytest.fixture(scope="module")
def keys():
    return [str(secret_key(seed).as_public()) for seed in range(1, 6)]


def make_app(tmp_path, keys, enabled=True, **overrides):
    overrides.setdefault("clan_wallet_network", "signet")
    settings = LiveSettings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'wallet.db'}",
        session_secret="a" * 64,
        public_origin=ORIGIN,
        rp_id="localhost",
        static_directory=None,
        clan_wallets_enabled=enabled,
        clan_wallet_oversight_keys=keys[0] if enabled else "",
        **overrides,
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.security.engine)
    return app


@pytest.fixture
def wallet_app(tmp_path, keys):
    """Every statement is checked against the web role's production grants."""
    app = make_app(tmp_path, keys)
    grants = GrantChecker()
    grants.watch(app.state.security.engine, "web")
    yield app
    grants.assert_clean()
    app.state.security.engine.dispose()


def three_signer_clan(app):
    owner, *_ = signup(app, "Organizer")
    second, *_ = signup(app, "Second Signer")
    third, *_ = signup(app, "Third Signer")
    member, *_ = signup(app, "Plain Member")
    cid = clan(owner)
    join(owner, second, cid)
    join(owner, third, cid)
    join(owner, member, cid, signer=False)
    return cid, [owner, second, third], member


def phone_code(view):
    """What a phone does: rebuild the wallet from the returned keys and compute the code."""
    policy = view["policy"]
    return ClanPolicy.create(
        network=policy["network"],
        oversight=policy["oversight"],
        signers=policy["signers"],
        recovery_threshold=policy["recovery_threshold"],
        recovery_blocks=policy["recovery_blocks"],
    ).wallet_code()


def test_wallets_are_off_unless_configured(tmp_path, keys):
    app = make_app(tmp_path, keys, enabled=False)
    owner, *_ = signup(app, "Organizer")
    cid = clan(owner)
    view = owner.get(f"/api/clans/{cid}/wallet").json()
    assert view["enabled"] is False and view["status"] == "not_started"
    assert owner.post(f"/api/clans/{cid}/wallet/keys", json={"key": keys[1]}).status_code == 503
    app.state.security.engine.dispose()


def test_the_custody_notice_matches_how_money_moves(tmp_path, keys):
    from fastapi.testclient import TestClient
    from test_live_app import ORIGIN

    for enabled, words in ((True, "its own Bitcoin wallet"), (False, "Afribit runs")):
        (tmp_path / str(enabled)).mkdir()
        app = make_app(tmp_path / str(enabled), keys, enabled=enabled)
        notice = TestClient(app, base_url=ORIGIN).get("/api/session").json()["custody_notice"]
        assert words in notice
        app.state.security.engine.dispose()


def test_enabling_wallets_requires_a_valid_oversight_key():
    with pytest.raises(ValueError, match="oversight"):
        LiveSettings(
            environment="test",
            database_url="sqlite://",
            session_secret="a" * 64,
            public_origin=ORIGIN,
            rp_id="localhost",
            clan_wallets_enabled=True,
            clan_wallet_oversight_keys="not a key",
        )


def test_signatories_register_keys_and_confirm_the_same_wallet(wallet_app, keys):
    cid, signers, member = three_signer_clan(wallet_app)
    route = f"/api/clans/{cid}/wallet"

    assert member.post(route + "/keys", json={"key": keys[4]}).status_code == 403
    first = signers[0].post(route + "/keys", json={"key": keys[1]})
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "collecting_keys"
    assert first.json()["policy"] is None
    assert first.json()["me"]["key"] == keys[1]
    # The same key again changes nothing.
    assert signers[0].post(route + "/keys", json={"key": keys[1]}).json() == first.json()
    signers[1].post(route + "/keys", json={"key": keys[2]})
    view = signers[2].post(route + "/keys", json={"key": keys[3]}).json()

    assert view["status"] == "confirming"
    assert view["threshold"] == 2 and view["recovery_days"] == 182
    assert view["policy"]["oversight"] == [keys[0]]
    assert sorted(view["policy"]["signers"]) == sorted(keys[1:4])
    code = phone_code(view)
    assert view["wallet_code"] == code
    # Every member, not only signatories, can see the wallet being set up.
    assert member.get(route).json()["wallet_code"] == code

    assert member.post(route + "/confirm", json={"wallet_code": code}).status_code == 403
    for signer in signers[:2]:
        assert signer.post(route + "/confirm", json={"wallet_code": code}).status_code == 200
    assert signers[0].get(route).json()["status"] == "confirming"
    final = signers[2].post(route + "/confirm", json={"wallet_code": code}).json()
    assert final["status"] == "active" and final["activated_at"]
    assert all(s["confirmed"] for s in final["signers"])

    # Once active, keys are fixed: a roster change needs a new wallet.
    response = signers[0].post(route + "/keys", json={"key": keys[4]})
    assert response.status_code == 409


def test_a_different_wallet_code_is_refused_and_recorded(wallet_app, keys):
    cid, signers, member = three_signer_clan(wallet_app)
    route = f"/api/clans/{cid}/wallet"
    for signer, key in zip(signers, keys[1:4], strict=True):
        signer.post(route + "/keys", json={"key": key})
    wrong = "qqqqqqqq"
    response = signers[1].post(route + "/confirm", json={"wallet_code": wrong})
    assert response.status_code == 409
    assert "Do not use this wallet" in response.json()["detail"]
    assert signers[1].post(route + "/confirm", json={"wallet_code": "short"}).status_code == 422
    with wallet_app.state.security.db() as db:
        alarm = db.scalar(select(AuditEvent).where(AuditEvent.event_type == "wallet_code_mismatch"))
        assert alarm.payload["phone_code"] == wrong
    # Every member is shown it, with the generation of the wallet it was about.
    (shown,) = member.get(route + "/alarms").json()
    assert shown["kind"] == "wallet_code_mismatch" and shown["generation"] == 1
    assert shown["detail"]["phone_code"] == wrong
    assert "different wallet code" in shown["message"]
    assert signers[0].get(route).json()["alarms_recent"] == 1


def test_changing_a_key_before_activation_resets_confirmations(wallet_app, keys):
    cid, signers, _ = three_signer_clan(wallet_app)
    route = f"/api/clans/{cid}/wallet"
    for signer, key in zip(signers, keys[1:4], strict=True):
        signer.post(route + "/keys", json={"key": key})
    old = signers[0].get(route).json()["wallet_code"]
    assert signers[0].post(route + "/confirm", json={"wallet_code": old}).status_code == 200

    view = signers[2].post(route + "/keys", json={"key": keys[4]}).json()
    assert view["status"] == "confirming"
    assert view["wallet_code"] != old
    assert not any(s["confirmed"] for s in view["signers"])
    assert signers[0].post(route + "/confirm", json={"wallet_code": old}).status_code == 409


def test_several_oversight_keys_can_be_configured(tmp_path, keys):
    two = secret_key(11).as_public()
    settings = dict(
        environment="test",
        database_url="sqlite://",
        session_secret="a" * 64,
        public_origin=ORIGIN,
        rp_id="localhost",
        clan_wallets_enabled=True,
        clan_wallet_network="signet",
    )
    assert LiveSettings(
        **settings, clan_wallet_oversight_keys=f"{keys[0]}, {two}"
    ).oversight_keys == [
        keys[0],
        str(two),
    ]
    with pytest.raises(ValueError, match="one to three"):
        LiveSettings(**settings, clan_wallet_oversight_keys=f"{keys[0]},{keys[0]}")


def test_unsafe_keys_are_refused(wallet_app, keys):
    cid, signers, _ = three_signer_clan(wallet_app)
    route = f"/api/clans/{cid}/wallet/keys"
    # The oversight key, a private key, or someone else's key cannot be registered.
    assert signers[0].post(route, json={"key": keys[0]}).status_code == 400
    private = str(secret_key(9))
    assert signers[0].post(route, json={"key": private}).status_code == 400
    assert signers[0].post(route, json={"key": keys[1]}).status_code == 200
    assert signers[1].post(route, json={"key": keys[1]}).status_code == 409
