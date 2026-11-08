"""Real WebAuthn proofs, same-account recovery and delayed clan authorization."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from test_live_app import Authenticator, clan, client, join, signup
from test_live_app import live as live

from clans.live_models import Passkey
from clans.recovery_models import AccessRecovery, AccessRecoveryApproval, Contact


def group(app):
    owner, key, kit, session = signup(app, "Member needing help")
    cid = clan(owner)
    a, key_a, _, _ = signup(app, "Signatory A")
    b, key_b, _, _ = signup(app, "Signatory B")
    join(owner, a, cid)
    join(owner, b, cid)
    return owner, key, kit, session, cid, a, key_a, b, key_b


def start(app, handle):
    lost, key = client(app), Authenticator()
    options = lost.post("/api/auth/clan-recovery/options", json={"handle": handle})
    assert options.status_code == 200, options.text
    options = options.json()
    result = lost.post(
        "/api/auth/clan-recovery/verify",
        json={
            "challenge_id": options["challenge_id"],
            "credential": key.registration(options["options"]["challenge"]),
        },
    )
    assert result.status_code == 200, result.text
    return lost, key, result.json()["request_id"], result.json()["device_code"]


def approve(who, key, cid, rid, code):
    prefix = f"/api/clans/{cid}/access-recoveries/{rid}/approval"
    options = who.post(prefix + "/options", json={"member_checked": True, "device_code": code})
    assert options.status_code == 200, options.text
    options = options.json()
    result = who.post(
        prefix + "/verify",
        json={
            "challenge_id": options["challenge_id"],
            "credential": key.assertion(options["options"]["challenge"]),
        },
    )
    assert result.status_code == 200, result.text
    return result.json()


def clock(monkeypatch, at):
    monkeypatch.setattr("clans.access_api.now_iso", lambda: at.isoformat())
    monkeypatch.setattr("clans.access_service.now_iso", lambda: at.isoformat())


def finish(who, key, rid):
    state = who.get(f"/api/auth/clan-recovery/{rid}").json()
    headers = {"X-Recovery-CSRF-Token": state["csrf"]}
    options = who.post(f"/api/auth/clan-recovery/{rid}/finish/options", json={}, headers=headers)
    if options.status_code != 200:
        return options
    options = options.json()
    return who.post(
        f"/api/auth/clan-recovery/{rid}/finish/verify",
        headers=headers,
        json={
            "challenge_id": options["challenge_id"],
            "credential": key.assertion(options["options"]["challenge"]),
        },
    )


def test_phone_required_private_and_never_a_login_factor(live):
    who = client(live)
    assert (
        who.post(
            "/api/auth/register/options", json={"display_name": "Someone", "accepted_terms": True}
        ).status_code
        == 422
    )
    assert (
        who.post(
            "/api/auth/register/options",
            json={"display_name": "Someone", "accepted_terms": True, "phone_number": "0700000001"},
        ).status_code
        == 422
    )
    owner, _, _, _, cid, a, *_ = group(live)
    own = owner.get("/api/session").json()["user"]
    assert own["phone_number"] == "+254700000001" and own["contact_complete"]
    detail = a.get(f"/api/clans/{cid}").json()
    assert "+254700000001" not in str(detail)
    assert all("phone_number" not in member for member in detail["members"])
    assert (
        who.post("/api/auth/login/verify", json={"phone_number": "+254700000001"}).status_code
        == 422
    )


def test_recovery_needs_prior_member_consent(live):
    _, _, kit, session, *_ = group(live)
    with live.state.security.db() as db:
        db.get(Contact, session["user"]["id"]).recovery_consent_at = None
    assert (
        client(live)
        .post("/api/auth/clan-recovery/options", json={"handle": kit["handle"]})
        .status_code
        == 409
    )


def test_same_account_and_membership_return_after_full_48_hours(live, monkeypatch):
    owner, _, kit, original, cid, a, key_a, b, key_b = group(live)
    lost, new_key, rid, code = start(live, kit["handle"])
    assert lost.get("/api/session").json()["user"] is None
    assert finish(lost, new_key, rid).status_code == 409
    assert approve(a, key_a, cid, rid, code)["status"] == "pending"
    assert approve(b, key_b, cid, rid, code)["status"] == "waiting"
    ready = datetime.fromisoformat(lost.get(f"/api/auth/clan-recovery/{rid}").json()["ready_at"])
    assert ready > datetime.now(UTC) + timedelta(hours=47, minutes=59)
    clock(monkeypatch, ready - timedelta(seconds=1))
    assert finish(lost, new_key, rid).status_code == 409
    clock(monkeypatch, ready + timedelta(seconds=1))
    result = finish(lost, new_key, rid)
    assert result.status_code == 200, result.text
    assert len(result.json()["recovery_codes"]) == 1
    restored = lost.get("/api/session").json()
    assert restored["user"]["id"] == original["user"]["id"]
    assert [g["id"] for g in restored["clans"]] == [cid]
    assert owner.get("/api/session").json()["user"] is None
    with live.state.security.db() as db:
        active = db.scalars(
            select(Passkey).where(
                Passkey.user_id == original["user"]["id"], Passkey.active.is_(True)
            )
        ).all()
        assert len(active) == 1


def test_member_cannot_create_another_clan_during_recovery(live):
    owner, _, kit, _, _, _, _, _, _ = group(live)
    start(live, kit["handle"])
    response = owner.post(
        "/api/clans",
        json={
            "name": "Another clan",
            "target_signers": 3,
            "member_vote_quorum": 2,
            "be_signer": True,
            "accepted_custody": True,
        },
        headers={"Idempotency-Key": "another-clan-attempt-001"},
    )
    assert response.status_code in {403, 409}


def test_owner_blocks_with_fresh_passkey_and_cannot_be_overruled(live, monkeypatch):
    owner, key, kit, _, cid, a, key_a, b, key_b = group(live)
    lost, replacement, rid, code = start(live, kit["handle"])
    approve(a, key_a, cid, rid, code)
    approve(b, key_b, cid, rid, code)
    prefix = f"/api/account/access-recoveries/{rid}/block"
    options = owner.post(prefix + "/options", json={}).json()
    result = owner.post(
        prefix + "/verify",
        json={
            "challenge_id": options["challenge_id"],
            "credential": key.assertion(options["options"]["challenge"]),
        },
    )
    assert result.status_code == 200
    clock(monkeypatch, datetime.now(UTC) + timedelta(hours=50))
    assert lost.get(f"/api/auth/clan-recovery/{rid}").json()["status"] == "blocked"
    assert finish(lost, replacement, rid).status_code == 409
    assert (
        a.post(
            f"/api/clans/{cid}/access-recoveries/{rid}/approval/options",
            json={"member_checked": True, "device_code": code},
        ).status_code
        == 403
    )


def test_unauthorized_people_wrong_codes_and_wrong_keys_cannot_approve(live):
    owner, _, kit, _, cid, a, key_a, _, _ = group(live)
    lost, new_key, rid, code = start(live, kit["handle"])
    outsider, _, _, _ = signup(live, "Not a member")
    prefix = f"/api/clans/{cid}/access-recoveries/{rid}/approval"
    body = {"member_checked": True, "device_code": code}
    assert outsider.post(prefix + "/options", json=body).status_code == 403
    assert owner.post(prefix + "/options", json=body).status_code == 403
    assert (
        a.post(prefix + "/options", json={**body, "device_code": "0000-0000-0000"}).status_code
        == 400
    )
    options = a.post(prefix + "/options", json=body).json()
    assert (
        a.post(
            prefix + "/verify",
            json={
                "challenge_id": options["challenge_id"],
                "credential": new_key.assertion(options["options"]["challenge"]),
            },
        ).status_code
        == 400
    )
    assert lost.get("/api/session").json()["user"] is None


def test_claim_cookie_csrf_and_replacement_key_are_required(live):
    _, _, kit, _, cid, a, key_a, b, key_b = group(live)
    lost, key, rid, code = start(live, kit["handle"])
    stranger = client(live)
    assert stranger.get(f"/api/auth/clan-recovery/{rid}").status_code == 403
    assert lost.post(f"/api/auth/clan-recovery/{rid}/finish/options", json={}).status_code == 403
    options = stranger.post(
        "/api/auth/clan-recovery/resume/options", json={"request_id": rid}
    ).json()
    wrong = Authenticator()
    assert (
        stranger.post(
            "/api/auth/clan-recovery/resume/verify",
            json={
                "challenge_id": options["challenge_id"],
                "credential": wrong.assertion(options["options"]["challenge"]),
            },
        ).status_code
        == 400
    )
    options = stranger.post(
        "/api/auth/clan-recovery/resume/options", json={"request_id": rid}
    ).json()
    assert (
        stranger.post(
            "/api/auth/clan-recovery/resume/verify",
            json={
                "challenge_id": options["challenge_id"],
                "credential": key.assertion(options["options"]["challenge"]),
            },
        ).status_code
        == 200
    )
    assert lost.get(f"/api/auth/clan-recovery/{rid}").status_code == 403
    approve(a, key_a, cid, rid, code)
    approve(b, key_b, cid, rid, code)


def test_revoked_or_forged_guardian_proofs_restart_checks(live):
    _, _, kit, _, cid, a, key_a, b, key_b = group(live)
    lost, _, rid, code = start(live, kit["handle"])
    approve(a, key_a, cid, rid, code)
    approve(b, key_b, cid, rid, code)
    with live.state.security.db() as db:
        proof = db.scalar(
            select(AccessRecoveryApproval).where(AccessRecoveryApproval.recovery_id == rid)
        )
        proof.proof = {**proof.proof, "digest": "0" * 64}
    state = lost.get(f"/api/auth/clan-recovery/{rid}").json()
    assert state["status"] == "pending" and state["ready_at"] is None
    with live.state.security.db() as db:
        row = db.get(AccessRecovery, rid)
        assert row.status == "pending"


def test_new_membership_cannot_be_gained_during_recovery(live):
    owner, _, kit, _, cid, a, key_a, b, key_b = group(live)
    lost, _, rid, code = start(live, kit["handle"])
    approve(a, key_a, cid, rid, code)
    approve(b, key_b, cid, rid, code)
    other, _, _, _ = signup(live, "Other organizer")
    second = clan(other)
    invite = other.post(f"/api/clans/{second}/invitations", json={"is_signer": False}).json()
    response = owner.post(
        "/api/invitations/accept",
        json={
            "token": invite["token"],
            "accepted_custody": True,
        },
    )
    assert response.status_code in {403, 409}
    assert lost.get(f"/api/auth/clan-recovery/{rid}").json()["status"] == "waiting"


def test_contact_changes_require_an_own_fresh_passkey(live):
    who, key, _, _ = signup(live)
    details = {
        "phone_number": "+254711111111",
        "lightning_address": "member@blink.sv",
        "accepted_recovery": True,
    }
    options = who.post("/api/account/contact/options", json=details).json()
    assert who.get("/api/session").json()["user"]["phone_number"] == "+254700000001"
    result = who.post(
        "/api/account/contact/verify",
        json={
            "challenge_id": options["challenge_id"],
            "credential": key.assertion(options["options"]["challenge"]),
        },
    )
    assert result.status_code == 200
    own = who.get("/api/session").json()["user"]
    assert (
        own["phone_number"] == details["phone_number"]
        and own["lightning_address"] == details["lightning_address"]
    )
