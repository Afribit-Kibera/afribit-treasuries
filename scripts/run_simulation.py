"""Run a disposable six-person circular grant through the API; no real funds."""

import json
from datetime import UTC, datetime
from pathlib import Path

from clans.api import create_app
from clans.config import Settings
from clans.db import Base, make_engine
from clans.seed import seed_demo
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


def main() -> None:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    settings = Settings(demo_auth_enabled=True, simulation_enabled=True)
    app = create_app(settings, engine)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        identities = seed_demo(session)
        session.commit()
    checks = []
    with TestClient(app) as client:

        def headers(persona="chair", key="start"):
            return {
                "Authorization": "Bearer "
                + identities["users"][persona]["bearer_token"],
                "Idempotency-Key": key,
            }

        root = f"/api/v1/clans/{identities['clan_id']}/simulations"
        response = client.post(root, headers=headers(), json={})
        assert response.status_code == 201
        path = root + "/" + response.json()["id"]
        counter = 0

        def command(action, persona="chair", expected=200, key=None, **fields):
            nonlocal counter
            counter += 1
            response = client.post(
                path + "/commands",
                headers=headers(persona, key or str(counter)),
                json={"action": action, **fields},
            )
            assert response.status_code == expected, (action, response.status_code)
            return response.json()

        run = command("contribute", amount_sats=10000, key="deposit-once")
        retry = command("contribute", amount_sats=10000, key="deposit-once")
        assert run == retry
        checks.append("Contribution retry credited once")
        run = command(
            "request_grant",
            "beneficiary",
            amount_sats=5000,
            purpose="Test business stock",
        )
        gid = next(iter(run["state"]["grants"]))
        for voter in ["chair", "treasurer", "member"]:
            command("vote", voter, grant_id=gid, choice="approve")
        command("accept_terms", "beneficiary", grant_id=gid)
        run = command(
            "freeze_intent",
            grant_id=gid,
            destination="sim:beneficiary",
            fee_ceiling_sats=10,
        )
        old_hash = run["state"]["grants"][gid]["intent"]["sha256"]
        command("approve_intent", grant_id=gid, intent_sha256=old_hash)
        command("execute", grant_id=gid, intent_sha256=old_hash, expected=409)
        checks.append("Member votes and one signer cannot execute")
        run = command(
            "freeze_intent",
            grant_id=gid,
            destination="sim:changed-destination",
            fee_ceiling_sats=10,
        )
        intent = run["state"]["grants"][gid]["intent"]
        assert (
            intent["sha256"] != old_hash
            and not run["state"]["grants"][gid]["approvals"]
        )
        command(
            "approve_intent",
            "treasurer",
            grant_id=gid,
            intent_sha256=old_hash,
            expected=409,
        )
        checks.append("Destination change invalidates earlier approvals")
        for signer in ["chair", "treasurer"]:
            command(
                "approve_intent", signer, grant_id=gid, intent_sha256=intent["sha256"]
            )
        command(
            "execute", grant_id=gid, intent_sha256=intent["sha256"], actual_fee_sats=2
        )
        command(
            "execute",
            grant_id=gid,
            intent_sha256=intent["sha256"],
            actual_fee_sats=2,
            expected=409,
        )
        checks.append(
            "Two signers permit one simulated payout; repeat execution rejected"
        )
        command(
            "repay",
            "beneficiary",
            grant_id=gid,
            amount_sats=1000,
            settlement_reference="sim:direct",
        )
        command(
            "repay",
            "beneficiary",
            grant_id=gid,
            amount_sats=1000,
            settlement_reference="sim:direct",
            expected=409,
        )
        run = command(
            "repay",
            "beneficiary",
            grant_id=gid,
            amount_sats=2000,
            method="otc",
            remitter_user_id=identities["users"]["otc_merchant"]["id"],
            settlement_reference="sim:otc",
        )
        repayment = run["state"]["grants"][gid]["repayments"][-1]
        assert repayment["beneficiary_id"] != repayment["remitter_id"]
        checks.append(
            "Direct and OTC recovery credited once, beneficiary/remitter kept separate"
        )
        run = command(
            "propose_amendment",
            grant_id=gid,
            new_outstanding_minor=1500,
            reason="Clan-approved support",
        )
        aid = run["state"]["grants"][gid]["amendments"][0]["id"]
        for voter in ["chair", "treasurer", "member"]:
            run = command(
                "vote_amendment",
                voter,
                grant_id=gid,
                amendment_id=aid,
                choice="approve",
            )
        assert run["state"]["grants"][gid]["forgiven_minor"] == 500
        checks.append(
            "Quorum forgives 500 sats of obligation without adding treasury funds"
        )
        run = command(
            "request_grant",
            "member",
            amount_sats=6000,
            purpose="Reuse recovered capital",
        )
        second_id = next(g for g in run["state"]["grants"] if g != gid)
        for voter in ["chair", "treasurer", "secretary"]:
            command("vote", voter, grant_id=second_id, choice="approve")
        command("accept_terms", "member", grant_id=second_id)
        run = command(
            "freeze_intent",
            grant_id=second_id,
            destination="sim:second-member",
            fee_ceiling_sats=10,
        )
        intent_hash = run["state"]["grants"][second_id]["intent"]["sha256"]
        for signer in ["chair", "treasurer"]:
            command(
                "approve_intent", signer, grant_id=second_id, intent_sha256=intent_hash
            )
        run = command(
            "execute", grant_id=second_id, intent_sha256=intent_hash, actual_fee_sats=2
        )
        state = run["state"]
        assert state["balance_sats"] == state["available_sats"] == 1996
        assert state["reserved_sats"] == 0
        treasury = 0
        for entry in state["journal"]:
            assert (
                sum(line["debit_sats"] - line["credit_sats"] for line in entry["lines"])
                == 0
            )
            treasury += sum(
                line["debit_sats"] - line["credit_sats"]
                for line in entry["lines"]
                if line["account"] == "treasury"
            )
        assert treasury == state["balance_sats"]
        assert not run["real_payments_enabled"]
        checks.append(
            "Recovered capital supports a second 6,000-sat grant; journal reconciles"
        )
    engine.dispose()
    report = {
        "observed_at_utc": datetime.now(UTC).isoformat(),
        "mode": "simulation",
        "transport": "FastAPI TestClient",
        "database": "disposable_in_memory_sqlite",
        "synthetic_users": 6,
        "clan_members": 5,
        "signers": 3,
        "member_quorum": 3,
        "signer_threshold": 2,
        "simulated_contributions_sats": state["contributed_sats"],
        "simulated_disbursements_sats": state["disbursed_sats"],
        "simulated_recovery_sats": state["recovered_sats"],
        "simulated_fees_sats": state["fees_sats"],
        "simulated_final_balance_sats": state["balance_sats"],
        "first_grant_outstanding_sats": state["grants"][gid]["outstanding_minor"],
        "checks": checks,
        "real_funds_moved": False,
        "real_invoice_credited": False,
    }
    target = Path("docs/test-results/2026-11-02-circular-simulation.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
