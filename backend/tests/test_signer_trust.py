"""Independent key pins defeat a forged web-controlled signatory registry."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import select
from test_live_app import live as live
from test_live_app import signup
from test_money import approve, prepared
from test_money import money as money

from clans.dispatch_security import validate_worker_settings
from clans.live_models import Grant, Passkey
from clans.live_security import b64
from clans.money_models import Balance, Payout, WorkerStatus
from clans.money_service import canonical_json
from clans.signer_trust import DOMAIN, fingerprint


def trust(money, data, tmp_path):
    app, worker, _ = money
    root = Ed25519PrivateKey.generate()
    worker.settings = worker.settings.model_copy(
        update={
            "signer_trust_required": True,
            "signer_trust_public_key": b64(root.public_key().public_bytes_raw()),
            "signer_trust_directory": tmp_path,
        }
    )
    with app.state.security.db() as db:
        grant = db.get(Grant, data[7])
        manifest = {
            "domain": DOMAIN,
            "namespace": worker.settings.provider_namespace,
            "clan_id": grant.clan_id,
            "node": worker.settings.expected_node_pubkey,
            "store": worker.settings.btcpay_store_id,
            "policy": grant.policy_snapshot,
            "members": sorted([*grant.eligible_voters, grant.beneficiary_id]),
            "signers": {
                uid: [
                    {
                        "credential_id": key.credential_id,
                        "public_key_sha256": fingerprint(key.public_key),
                    }
                    for key in db.scalars(
                        select(Passkey).where(Passkey.user_id == uid, Passkey.active.is_(True))
                    ).all()
                ]
                for uid in [*grant.eligible_signers, grant.beneficiary_id]
            },
            "issued_at": datetime.now(UTC).isoformat(),
            "expires_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        }
    path = tmp_path / (data[6] + ".json")

    def save():
        path.write_text(
            json.dumps(
                {
                    "manifest": manifest,
                    "signature": b64(root.sign(canonical_json(manifest).encode())),
                }
            )
        )

    save()
    return manifest, path, save


def queue(data):
    approve(data[2], data[3], data[8])
    approve(data[4], data[5], data[8])


def test_independently_pinned_keys_allow_payment(money, tmp_path):
    data = prepared(money)
    trust(money, data, tmp_path)
    queue(data)
    money[1].tick()
    assert money[2].pay_calls == 1
    with money[0].state.security.db() as db:
        from clans.money_models import DispatchAuthorization

        assert len(db.scalar(select(DispatchAuthorization)).signer_trust_digest) == 64


def test_production_cannot_disable_independent_trust(money):
    settings = money[1].settings.model_copy(
        update={
            "environment": "production",
            "signer_trust_required": False,
        }
    )
    with pytest.raises(ValueError, match="offline signer trust"):
        validate_worker_settings(settings)


def test_replaced_database_key_and_valid_attacker_signature_cannot_send(money, tmp_path):
    app, worker, network = money
    data = prepared(money)
    trust(money, data, tmp_path)
    _, attacker, _, _ = signup(app, "Attacker key holder")
    with app.state.security.db() as db:
        attacker_public = db.scalar(
            select(Passkey).where(Passkey.credential_id == b64(attacker.id))
        ).public_key
        target = db.scalar(select(Passkey).where(Passkey.credential_id == b64(data[3].id)))
        target.public_key, target.sign_count = attacker_public, 0
    attacker.id = data[3].id
    # Both assertions now validate against the mutable web registry. Only the
    # independent manifest distinguishes the substituted key from the real one.
    approve(data[2], attacker, data[8])
    approve(data[4], data[5], data[8])
    worker.tick()
    assert network.pay_calls == 0
    with app.state.security.db() as db:
        assert db.get(Balance, data[6]).reserved_msat == 101000
        assert db.get(WorkerStatus, "treasury").status == "ready"
        assert db.scalar(select(Payout)).last_error == "clan_verification_required"


@pytest.mark.parametrize("failure", ["missing", "tampered", "expired", "namespace", "policy"])
def test_untrusted_manifest_cannot_dispatch(money, tmp_path, failure):
    data = prepared(money)
    manifest, path, save = trust(money, data, tmp_path)
    queue(data)
    if failure == "missing":
        path.unlink()
    elif failure == "tampered":
        envelope = json.loads(path.read_text())
        envelope["manifest"]["members"].append("forged")
        path.write_text(json.dumps(envelope))
    else:
        if failure == "expired":
            manifest["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        elif failure == "namespace":
            manifest["namespace"] = "wrong-environment"
        else:
            manifest["policy"]["threshold"] = 1
        save()
    money[1].tick()
    assert money[2].pay_calls == 0


def test_already_dispatched_payment_reconciles_after_manifest_is_removed(money, tmp_path):
    app, worker, network = money
    data = prepared(money)
    _, path, _ = trust(money, data, tmp_path)
    queue(data)
    network.pending_send = True
    worker.tick()
    path.unlink()
    network.outgoing[data[9]]["status"] = "Complete"
    worker.tick()
    assert network.pay_calls == 1
    with app.state.security.db() as db:
        assert db.scalar(select(Payout)).status == "settled"
