"""Real cryptographic WebAuthn tests and persisted membership/governance controls."""

import hashlib
import json
import os
import secrets

import cbor2
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from clans.db import Base
from clans.live_app import create_app
from clans.live_config import LiveSettings
from clans.live_models import Invitation, LoginSession, Treasury
from clans.live_security import b64
from clans.models import Membership, User

ORIGIN = "http://localhost:8410"


class Authenticator:
    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.id = secrets.token_bytes(32)
        self.count = 0

    def client_data(self, challenge, kind, origin=ORIGIN):
        return json.dumps(
            {"type": kind, "challenge": challenge, "origin": origin, "crossOrigin": False}
        ).encode()

    def registration(self, challenge, *, origin=ORIGIN, uv=True):
        data = self.client_data(challenge, "webauthn.create", origin)
        point = self.key.public_key().public_numbers()
        cose = {
            1: 2,
            3: -7,
            -1: 1,
            -2: point.x.to_bytes(32, "big"),
            -3: point.y.to_bytes(32, "big"),
        }
        auth = (
            hashlib.sha256(b"localhost").digest()
            + bytes([0x45 if uv else 0x41])
            + bytes(4)
            + bytes(16)
            + len(self.id).to_bytes(2, "big")
            + self.id
            + cbor2.dumps(cose)
        )
        attestation = cbor2.dumps({"fmt": "none", "authData": auth, "attStmt": {}})
        return {
            "id": b64(self.id),
            "rawId": b64(self.id),
            "type": "public-key",
            "response": {"clientDataJSON": b64(data), "attestationObject": b64(attestation)},
        }

    def assertion(self, challenge):
        self.count += 1
        data = self.client_data(challenge, "webauthn.get")
        auth = hashlib.sha256(b"localhost").digest() + b"\x05" + self.count.to_bytes(4, "big")
        signature = self.key.sign(auth + hashlib.sha256(data).digest(), ec.ECDSA(hashes.SHA256()))
        return {
            "id": b64(self.id),
            "rawId": b64(self.id),
            "type": "public-key",
            "response": {
                "clientDataJSON": b64(data),
                "authenticatorData": b64(auth),
                "signature": b64(signature),
            },
        }


@pytest.fixture
def live(tmp_path):
    url = os.environ.get("CLANS_TEST_DATABASE_URL", f"sqlite:///{tmp_path / 'live.db'}")
    if not url.startswith("sqlite"):
        from sqlalchemy.engine import make_url

        assert make_url(url).database == "afribit_clans_tests", (
            "Tests require the isolated stage DB"
        )
    settings = LiveSettings(
        environment="test",
        database_url=url,
        session_secret="a" * 64,
        public_origin=ORIGIN,
        rp_id="localhost",
        static_directory=None,
    )
    app = create_app(settings)
    if not url.startswith("sqlite"):
        Base.metadata.drop_all(app.state.security.engine)
    Base.metadata.create_all(app.state.security.engine)
    yield app
    app.state.security.engine.dispose()


def client(app):
    return TestClient(app, base_url=ORIGIN, headers={"Origin": ORIGIN})


def signup(app, name="Real Member"):
    c = client(app)
    auth = Authenticator()
    opts = c.post(
        "/api/auth/register/options",
        json={
            "display_name": name,
            "username": "member_" + secrets.token_hex(6),
            "accepted_terms": True,
            "phone_number": "+254700000001",
            "accepted_recovery": True,
        },
    ).json()
    body = {
        "challenge_id": opts["challenge_id"],
        "credential": auth.registration(opts["options"]["challenge"]),
    }
    result = c.post("/api/auth/register/verify", json=body)
    assert result.status_code == 200, result.text
    state = c.get("/api/session").json()
    c.headers["X-CSRF-Token"] = state["csrf"]
    return c, auth, result.json(), state


def clan(c, *, count=3):
    response = c.post(
        "/api/clans",
        json={
            "name": "Real Treasury",
            "description": "Our purpose",
            "target_signers": count,
            "member_vote_quorum": 2,
            "be_signer": True,
            "accepted_custody": True,
        },
        headers={"Idempotency-Key": secrets.token_hex(16)},
    )
    assert response.status_code == 200, response.text
    return response.json()["clan_id"]


def join(organizer, member, clan_id, signer=True):
    invitation = organizer.post(
        f"/api/clans/{clan_id}/invitations", json={"is_signer": signer}
    ).json()
    response = member.post(
        "/api/invitations/accept",
        json={"token": invitation["token"], "accepted_custody": True, "accepted_signer": signer},
    )
    assert response.status_code == 200, response.text
    return invitation


def test_no_mock_auth_or_starting_funds(live):
    c = client(live)
    assert c.get("/api/session").json()["user"] is None
    assert c.get("/api/v1/me", headers={"Authorization": "Bearer demo"}).status_code == 404
    c, _auth, kit, state = signup(live)
    assert len(kit["recovery_codes"]) == 1
    assert state["clans"] == []
    cid = clan(c)
    detail = c.get(f"/api/clans/{cid}").json()
    assert detail["available_sats"] == 0
    assert len(detail["members"]) == 1
    with live.state.security.db() as db:
        assert (
            db.scalar(select(func.count()).select_from(User).where(User.is_test_user.is_(True)))
            == 0
        )


def test_uv_origin_and_cookie_binding(live):
    c = client(live)
    auth = Authenticator()

    def options():
        return c.post(
            "/api/auth/register/options",
            json={
                "display_name": "Someone",
                "username": "someone",
                "accepted_terms": True,
                "phone_number": "+254700000002",
            },
        ).json()

    for origin, uv in (("https://evil.example", True), (ORIGIN, False)):
        opts = options()
        body = {
            "challenge_id": opts["challenge_id"],
            "credential": auth.registration(opts["options"]["challenge"], origin=origin, uv=uv),
        }
        assert c.post("/api/auth/register/verify", json=body).status_code == 400
    opts = options()
    body = {
        "challenge_id": opts["challenge_id"],
        "credential": auth.registration(opts["options"]["challenge"]),
    }
    assert client(live).post("/api/auth/register/verify", json=body).status_code == 400
    assert c.post("/api/auth/register/verify", json=body).status_code == 200
    assert c.post("/api/auth/register/verify", json=body).status_code == 400


def test_login_csrf_replay_and_headers(live):
    c, authenticator, _kit, _state = signup(live)
    assert c.post("/api/clans", json={}).status_code == 422
    assert (
        c.post("/api/onboarding/complete", json={}, headers={"X-CSRF-Token": "wrong"}).status_code
        == 403
    )
    assert (
        c.post(
            "/api/onboarding/complete", json={}, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert c.post("/api/auth/logout", json={}).status_code == 200
    assert c.get("/api/account/security").status_code == 401
    opts = c.post("/api/auth/login/options", json={}).json()
    body = {
        "challenge_id": opts["challenge_id"],
        "credential": authenticator.assertion(opts["options"]["challenge"]),
    }
    assert c.post("/api/auth/login/verify", json=body).status_code == 200
    assert c.post("/api/auth/login/verify", json=body).status_code == 400
    response = c.get("/api/session")
    assert response.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_recovery_is_one_use_and_revokes_old_access(live):
    c, old_auth, kit, state = signup(live)
    other = client(live)
    opts = other.post(
        "/api/auth/recover/options",
        json={"handle": kit["handle"], "code": kit["recovery_codes"][0]},
    ).json()
    replacement = Authenticator()
    body = {
        "challenge_id": opts["challenge_id"],
        "credential": replacement.registration(opts["options"]["challenge"]),
    }
    response = other.post("/api/auth/recover/verify", json=body)
    assert response.status_code == 200, response.text
    assert len(response.json()["recovery_codes"]) == 1
    assert c.get("/api/session").json()["user"] is None
    assert (
        other.post(
            "/api/auth/recover/options",
            json={"handle": kit["handle"], "code": kit["recovery_codes"][0]},
        ).status_code
        == 400
    )
    opts = c.post("/api/auth/login/options", json={}).json()
    assert (
        c.post(
            "/api/auth/login/verify",
            json={
                "challenge_id": opts["challenge_id"],
                "credential": old_auth.assertion(opts["options"]["challenge"]),
            },
        ).status_code
        == 400
    )
    assert other.get("/api/session").json()["user"]["id"] == state["user"]["id"]
    with live.state.security.db() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(LoginSession)
                .where(LoginSession.revoked.is_(False))
            )
            == 1
        )


@pytest.mark.parametrize("count", [3, 5, 7])
def test_signer_options_and_invitation_consent(live, count):
    owner, *_ = signup(live, "Organizer")
    member, *_ = signup(live, "Invited Member")
    cid = clan(owner, count=count)
    invitation = owner.post(f"/api/clans/{cid}/invitations", json={"is_signer": True}).json()
    with live.state.security.db() as db:
        assert db.scalar(select(func.count()).select_from(Membership)) == 1
        stored = db.get(Invitation, invitation["id"])
        assert stored.token_hash != invitation["token"]
    assert (
        member.post(
            "/api/invitations/accept",
            json={"token": invitation["token"], "accepted_custody": True, "accepted_signer": False},
        ).status_code
        == 400
    )
    assert (
        member.post(
            "/api/invitations/accept",
            json={"token": invitation["token"], "accepted_custody": True, "accepted_signer": True},
        ).status_code
        == 200
    )
    detail = owner.get(f"/api/clans/{cid}").json()
    assert detail["signer_threshold"] == count // 2 + 1
    assert detail["signer_count"] == 2
    stranger, *_ = signup(live, "Stranger")
    assert stranger.get(f"/api/clans/{cid}").status_code == 403
    assert (
        stranger.post(
            "/api/invitations/accept",
            json={"token": invitation["token"], "accepted_custody": True, "accepted_signer": True},
        ).status_code
        == 409
    )


def test_governance_and_no_phantom_payout(live):
    owner, *_ = signup(live, "Organizer")
    voter1, *_ = signup(live, "Voter One")
    voter2, *_ = signup(live, "Voter Two")
    cid = clan(owner)
    join(owner, voter1, cid)
    join(owner, voter2, cid)
    key = secrets.token_hex(16)
    body = {"purpose": "Inventory for our business", "amount_sats": 1500}
    response = owner.post(f"/api/clans/{cid}/grants", json=body, headers={"Idempotency-Key": key})
    assert response.status_code == 200, response.text
    assert (
        owner.post(f"/api/clans/{cid}/grants", json=body, headers={"Idempotency-Key": key}).json()
        == response.json()
    )
    assert (
        owner.post(
            f"/api/clans/{cid}/grants",
            json={**body, "amount_sats": 1},
            headers={"Idempotency-Key": key},
        ).status_code
        == 409
    )
    gid = response.json()["grant_id"]
    route = f"/api/clans/{cid}/grants/{gid}"
    assert owner.post(route + "/vote", json={"choice": "approve"}).status_code == 409
    assert owner.post(route + "/accept", json={}).status_code == 409
    for voter in (voter1, voter2):
        assert voter.post(route + "/vote", json={"choice": "approve"}).status_code == 200
    assert voter1.post(route + "/accept", json={}).status_code == 403
    assert owner.post(route + "/accept", json={}).json()["status"] == "awaiting_funding"
    detail = owner.get(f"/api/clans/{cid}").json()
    assert detail["balance_sats"] == 0
    assert detail["journal"] == []
    assert detail["grants"][0]["status"] == "awaiting_funding"
    assert owner.post(route + "/execute", json={}).status_code == 404
    with live.state.security.db() as db:
        assert db.get(Treasury, cid).reserved_sats == 0


def test_movement_cannot_be_switched_on(live):
    with pytest.raises(ValueError, match="Money movement"):
        create_app(live.state.security.settings.model_copy(update={"payouts_enabled": True}))


def test_opaque_token_is_not_public_invitation_lookup(live):
    c = client(live)
    for _ in range(8):
        assert (
            c.post(
                "/api/auth/recover/options", json={"handle": "clan-doesnotexist", "code": "0" * 24}
            ).status_code
            == 400
        )
    assert (
        c.post(
            "/api/auth/recover/options", json={"handle": "clan-doesnotexist", "code": "0" * 24}
        ).status_code
        == 429
    )


def test_security_changes_require_current_passkey(live):
    c, auth, kit, _ = signup(live)
    options = c.post("/api/account/reauth/options", json={"action": "add_passkey"}).json()
    assertion = auth.assertion(options["options"]["challenge"])
    result = c.post(
        "/api/account/reauth/verify",
        json={"challenge_id": options["challenge_id"], "credential": assertion},
    )
    assert result.status_code == 200, result.text
    registration = result.json()
    second = Authenticator()
    assert (
        c.post(
            "/api/account/passkeys/verify",
            json={
                "challenge_id": registration["challenge_id"],
                "credential": second.registration(registration["options"]["challenge"]),
            },
        ).status_code
        == 200
    )
    assert len(c.get("/api/account/security").json()["passkeys"]) == 2
    options = c.post("/api/account/reauth/options", json={"action": "recovery_codes"}).json()
    result = c.post(
        "/api/account/reauth/verify",
        json={
            "challenge_id": options["challenge_id"],
            "credential": auth.assertion(options["options"]["challenge"]),
        },
    )
    assert len(result.json()["recovery_codes"]) == 1
    assert (
        c.post(
            "/api/auth/recover/options",
            json={"handle": kit["handle"], "code": kit["recovery_codes"][0]},
        ).status_code
        == 400
    )
    assert c.get("/api/account/security").json()["recovery_codes_remaining"] == 1


def test_withdraw_and_revoke(live):
    owner, *_ = signup(live)
    outsider, *_ = signup(live)
    cid = clan(owner)
    invitation = owner.post(f"/api/clans/{cid}/invitations", json={"is_signer": True}).json()
    assert (
        owner.post(f"/api/clans/{cid}/invitations/{invitation['id']}/revoke", json={}).status_code
        == 200
    )
    assert (
        outsider.post("/api/invitations/preview", json={"token": invitation["token"]}).status_code
        == 404
    )
    assert (
        outsider.post(
            "/api/invitations/accept",
            json={"token": invitation["token"], "accepted_custody": True, "accepted_signer": True},
        ).status_code
        == 409
    )


def test_postgres_signer_cap_race(live):
    if live.state.security.engine.dialect.name != "postgresql":
        pytest.skip("Row-lock race verification requires PostgreSQL")
    from concurrent.futures import ThreadPoolExecutor

    owner, *_ = signup(live)
    first, *_ = signup(live)
    a, *_ = signup(live)
    b, *_ = signup(live)
    cid = clan(owner)
    join(owner, first, cid)
    invitations = [
        owner.post(f"/api/clans/{cid}/invitations", json={"is_signer": True}).json()
        for _ in range(2)
    ]

    def accept(pair):
        c, invitation = pair
        return c.post(
            "/api/invitations/accept",
            json={"token": invitation["token"], "accepted_custody": True, "accepted_signer": True},
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(accept, zip([a, b], invitations, strict=True)))
    assert sorted(results) == [200, 409]
    assert owner.get(f"/api/clans/{cid}").json()["signer_count"] == 3


def test_postgres_recovery_serializes_login_and_key_enrollment(live, monkeypatch):
    if live.state.security.engine.dialect.name != "postgresql":
        pytest.skip("Account revocation race verification requires PostgreSQL")
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    c, old_key, kit, _ = signup(live)
    opts = c.post("/api/account/reauth/options", json={"action": "add_passkey"}).json()
    enrollment = c.post(
        "/api/account/reauth/verify",
        json={
            "challenge_id": opts["challenge_id"],
            "credential": old_key.assertion(opts["options"]["challenge"]),
        },
    ).json()
    extra_key = Authenticator()
    enrollment_body = {
        "challenge_id": enrollment["challenge_id"],
        "credential": extra_key.registration(enrollment["options"]["challenge"]),
    }
    login_client = client(live)
    login = login_client.post("/api/auth/login/options", json={}).json()
    login_body = {
        "challenge_id": login["challenge_id"],
        "credential": old_key.assertion(login["options"]["challenge"]),
    }
    recovery_client = client(live)
    recovery = recovery_client.post(
        "/api/auth/recover/options",
        json={"handle": kit["handle"], "code": kit["recovery_codes"][0]},
    ).json()
    replacement = Authenticator()
    recovery_body = {
        "challenge_id": recovery["challenge_id"],
        "credential": replacement.registration(recovery["options"]["challenge"]),
    }
    locked, release = Event(), Event()
    original = live.state.security.registration

    def pause_recovery(credential, record):
        verified = original(credential, record)
        if record.kind == "recover":
            locked.set()
            assert release.wait(10)
        return verified

    monkeypatch.setattr(live.state.security, "registration", pause_recovery)
    with ThreadPoolExecutor(max_workers=3) as executor:
        recovering = executor.submit(
            recovery_client.post, "/api/auth/recover/verify", json=recovery_body
        )
        assert locked.wait(10)
        logging_in = executor.submit(login_client.post, "/api/auth/login/verify", json=login_body)
        enrolling = executor.submit(c.post, "/api/account/passkeys/verify", json=enrollment_body)
        release.set()
        assert recovering.result().status_code == 200
        assert logging_in.result().status_code == 400
        assert enrolling.result().status_code == 401
    assert c.get("/api/session").json()["user"] is None
    assert recovery_client.get("/api/account/security").json()["recovery_codes_remaining"] == 1
