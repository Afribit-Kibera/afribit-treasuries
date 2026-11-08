"""Regression tests for the five findings in the November adversarial review."""

import json
import secrets
import tarfile
from pathlib import Path

import pytest
from sqlalchemy import func, select
from test_live_app import Authenticator, clan, client, signup
from test_live_app import live as live
from test_money import money as money

from clans.live_models import IncomingPayment, Passkey
from clans.money_models import Balance, DepositReceipt, LedgerEntry


def test_audit_01_changed_pending_deposit_is_not_credited(money):
    app, worker, network = money
    victim, *_ = signup(app, "Victim")
    attacker, *_ = signup(app, "Attacker")
    victim_clan, attacker_clan = clan(victim), clan(attacker)
    response = victim.post(
        f"/api/clans/{victim_clan}/deposits",
        json={"amount_sats": 1000},
        headers={"Idempotency-Key": secrets.token_hex(16)},
    )
    assert response.status_code == 200
    incoming_id = response.json()["request_id"]
    worker.incoming(incoming_id)
    assert network.create_calls == 1
    # Explicit post-compromise assumption: UPDATE incoming_payments is granted
    # to the web role. This is not an ordinary-user API authorization bypass.
    with app.state.security.db() as db:
        incoming = db.get(IncomingPayment, incoming_id)
        assert incoming.status == "pending"
        incoming.clan_id = attacker_clan
    network.paid = True
    worker.incoming(incoming_id)
    with app.state.security.db() as db:
        assert db.get(Balance, victim_clan).balance_msat == 0
        assert db.get(Balance, attacker_clan).balance_msat == 0
        assert db.scalar(select(func.count()).select_from(DepositReceipt)) == 0
        assert db.scalar(select(LedgerEntry)) is None
        assert db.get(IncomingPayment, incoming_id).status == "review_required"
    assert network.pay_calls == 0


def test_audit_02_chunked_body_is_limited_before_parsing(live):
    c = client(live)
    payload = (
        json.dumps(
            {
                "display_name": "Body size probe",
                "username": "body_size_probe",
                "accepted_terms": True,
                "phone_number": "+254700000001",
                "accepted_recovery": True,
            }
        ).encode()
        + b" " * 131_072
    )
    # Same valid JSON, padded with whitespace; no memory exhaustion is attempted.
    fixed = c.post(
        "/api/auth/register/options", content=payload, headers={"Content-Type": "application/json"}
    )
    assert fixed.status_code == 413
    streamed = c.post(
        "/api/auth/register/options",
        content=iter([payload]),
        headers={"Content-Type": "application/json"},
    )
    assert "content-length" not in streamed.request.headers
    assert streamed.request.headers["transfer-encoding"] == "chunked"
    assert streamed.status_code == 413


def test_audit_03_anonymous_abuse_does_not_exhaust_valid_login_quota(live):
    victim, key, *_ = signup(live)
    options = victim.post("/api/auth/login/options", json={}).json()
    anonymous = client(live)  # Same source address, as on shared Wi-Fi/NAT.
    for _ in range(120):  # Invalid attempts have their own coarse abuse bucket.
        response = anonymous.post(
            "/api/auth/login/verify",
            json={
                "challenge_id": "missing",
                "credential": {},
            },
        )
        assert response.status_code == 400
    assert (
        anonymous.post(
            "/api/auth/login/verify", json={"challenge_id": "missing", "credential": {}}
        ).status_code
        == 429
    )
    response = victim.post(
        "/api/auth/login/verify",
        json={
            "challenge_id": options["challenge_id"],
            "credential": key.assertion(options["options"]["challenge"]),
        },
    )
    assert response.status_code == 200


def test_verification_attempt_limit_follows_ceremony_across_addresses(live):
    from fastapi.testclient import TestClient
    from test_live_app import ORIGIN

    victim, key, *_ = signup(live)
    options = victim.post("/api/auth/login/options", json={}).json()
    for index in range(5):
        caller = TestClient(
            live,
            base_url=ORIGIN,
            headers={"Origin": ORIGIN},
            client=(f"192.0.2.{index + 1}", 50000),
        )
        caller.cookies.update(victim.cookies)
        result = caller.post(
            "/api/auth/login/verify",
            json={"challenge_id": options["challenge_id"], "credential": {}},
        )
        assert result.status_code == 400
    result = victim.post(
        "/api/auth/login/verify",
        json={
            "challenge_id": options["challenge_id"],
            "credential": key.assertion(options["options"]["challenge"]),
        },
    )
    assert result.status_code == 429
    # A fresh ceremony remains available to the member.
    fresh = victim.post("/api/auth/login/options", json={}).json()
    assert (
        victim.post(
            "/api/auth/login/verify",
            json={
                "challenge_id": fresh["challenge_id"],
                "credential": key.assertion(fresh["options"]["challenge"]),
            },
        ).status_code
        == 200
    )


@pytest.mark.parametrize("concurrent", [False, True])
def test_audit_04_passkey_cap_is_checked_at_insertion(live, concurrent):
    if concurrent and live.state.security.engine.dialect.name != "postgresql":
        pytest.skip("Concurrent finalizations require PostgreSQL row locks")
    c, key, _, state = signup(live)

    def prepare():
        options = c.post("/api/account/reauth/options", json={"action": "add_passkey"})
        assert options.status_code == 200
        options = options.json()
        response = c.post(
            "/api/account/reauth/verify",
            json={
                "challenge_id": options["challenge_id"],
                "credential": key.assertion(options["options"]["challenge"]),
            },
        )
        assert response.status_code == 200, response.text
        return response.json(), list(c.cookies.jar)

    def finish(pending, expected=200):
        options, cookies = pending
        ceremony_client = client(live)
        ceremony_client.headers.update(c.headers)
        ceremony_client.cookies.clear()
        for cookie in cookies:
            ceremony_client.cookies.jar.set_cookie(cookie)
        new_key = Authenticator()
        response = ceremony_client.post(
            "/api/account/passkeys/verify",
            json={
                "challenge_id": options["challenge_id"],
                "credential": new_key.registration(options["options"]["challenge"]),
            },
        )
        if expected:
            assert response.status_code == expected, response.text
        return response.status_code

    for _ in range(8):
        finish(prepare())
    first, second = prepare(), prepare()  # Both authorized with nine existing keys.
    if concurrent:
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier

        gate = Barrier(2)

        def finalize(pending):
            gate.wait(timeout=10)
            return finish(pending, None)

        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(finalize, [first, second])) == [200, 409]
    else:
        finish(first)
        finish(second, 409)
    with live.state.security.db() as db:
        count = db.scalar(
            select(func.count())
            .select_from(Passkey)
            .where(
                Passkey.user_id == state["user"]["id"],
                Passkey.active.is_(True),
            )
        )
        assert count == 10


def test_audit_05_release_archive_excludes_unlisted_secrets(tmp_path):
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "scripts"))
    from release_archive import build_archive

    for directory in ["backend/src/clans", "scripts", "ops/secrets"]:
        (tmp_path / directory).mkdir(parents=True)
    (tmp_path / "backend/src/clans/safe.py").write_text("# safe", encoding="utf-8")
    (tmp_path / "ops/secrets/audit.key").write_text("NOT-A-REAL-SECRET", encoding="utf-8")
    manifest = {"backend": ["backend/src/clans/safe.py"], "public": []}
    (tmp_path / "scripts/release-files.json").write_text(json.dumps(manifest), encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "backend", "scripts"], check=True)
    target = tmp_path / "safe.tar.gz"
    build_archive(tmp_path, target)
    with tarfile.open(target) as archive:
        assert set(archive.getnames()) == {"backend/src/clans/safe.py", "release-manifest.json"}
        assert b"NOT-A-REAL-SECRET" not in b"".join(archive.extractfile(m).read() for m in archive)

    # Even explicitly listing and tracking a key cannot override the deny rules.
    import pytest

    manifest["backend"].append("ops/secrets/audit.key")
    (tmp_path / "scripts/release-files.json").write_text(json.dumps(manifest), encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-f", "ops/secrets/audit.key"], check=True)
    with pytest.raises(ValueError, match="Secret"):
        build_archive(tmp_path, target)
