import secrets

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from test_live_app import Authenticator, clan, client, signup
from test_live_app import live as live

from clans.live_models import Profile, RecoveryCode
from clans.models import Membership
from clans.recovery_words import encode, generate, hash_input


def test_recovery_words_match_bip39_vector_and_reject_mistakes():
    phrase = "abandon " * 11 + "about"
    assert encode(bytes(16)) == phrase
    assert hash_input("  " + phrase.upper() + "\n") == "recovery-words-v1:" + phrase
    assert len(generate().split()) == 12
    assert generate() != generate()
    with pytest.raises(ValueError):
        hash_input("abandon " * 12)
    with pytest.raises(ValueError):
        hash_input("missingword " * 12)


def test_old_recovery_kit_can_still_restore_account(live):
    _, _, kit, state = signup(live)
    old_code = secrets.token_hex(12)
    with live.state.security.db() as db:
        db.add(
            RecoveryCode(
                user_id=state["user"]["id"],
                code_hash=live.state.security.mac("recovery:" + old_code),
            )
        )
    lost = client(live)
    options = lost.post(
        "/api/auth/recover/options",
        json={
            "handle": kit["handle"].upper(),
            "code": "-".join(old_code[i : i + 6] for i in range(0, 24, 6)),
        },
    ).json()
    key = Authenticator()
    result = lost.post(
        "/api/auth/recover/verify",
        json={
            "challenge_id": options["challenge_id"],
            "credential": key.registration(options["options"]["challenge"]),
        },
    )
    assert result.status_code == 200
    assert len(result.json()["recovery_codes"][0].split()) == 12
    assert lost.get("/api/session").json()["user"]["id"] == state["user"]["id"]


def test_single_clan_rule_blocks_creation_and_invite_and_database_write(live):
    owner, _, _, state = signup(live)
    first = clan(owner)
    other, _, _, _ = signup(live)
    second = clan(other)
    create = owner.post(
        "/api/clans",
        json={
            "name": "Second clan",
            "target_signers": 3,
            "member_vote_quorum": 2,
            "be_signer": True,
            "accepted_custody": True,
        },
        headers={"Idempotency-Key": secrets.token_hex(16)},
    )
    assert create.status_code == 409
    invitation = other.post(f"/api/clans/{second}/invitations", json={"is_signer": False}).json()
    assert (
        owner.post(
            "/api/invitations/accept", json={"token": invitation["token"], "accepted_custody": True}
        ).status_code
        == 409
    )
    with pytest.raises(IntegrityError), live.state.security.db() as db:
        db.add(Membership(user_id=state["user"]["id"], clan_id=second))
        db.flush()
    assert owner.get("/api/session").json()["clans"][0]["id"] == first


def test_chosen_username_is_unique_and_change_needs_own_passkey(live):
    who, key, _, state = signup(live)
    body = {
        "display_name": "Amina",
        "username": "Amina23",
        "accepted_terms": True,
        "phone_number": "+254700000001",
    }
    opts = client(live).post("/api/auth/register/options", json=body)
    assert opts.status_code == 200
    auth = Authenticator()
    registration = opts.json()
    # Challenge cookie is intentionally on a different client: cannot complete it.
    assert (
        client(live)
        .post(
            "/api/auth/register/verify",
            json={
                "challenge_id": registration["challenge_id"],
                "credential": auth.registration(registration["options"]["challenge"]),
            },
        )
        .status_code
        == 400
    )
    options = who.post(
        "/api/account/reauth/options", json={"action": "username", "username": "Amina23"}
    ).json()
    result = who.post(
        "/api/account/reauth/verify",
        json={
            "challenge_id": options["challenge_id"],
            "credential": key.assertion(options["options"]["challenge"]),
        },
    )
    assert result.json() == {"handle": "amina23"}
    assert who.get("/api/session").json()["user"]["id"] == state["user"]["id"]
    assert client(live).post("/api/auth/register/options", json=body).status_code == 409
    with live.state.security.db() as db:
        assert (
            db.scalar(select(Profile.handle).where(Profile.user_id == state["user"]["id"]))
            == "amina23"
        )
