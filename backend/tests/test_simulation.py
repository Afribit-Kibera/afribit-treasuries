import hashlib
import secrets
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session

from clans.api import create_app
from clans.config import Settings
from clans.models import Membership, PolicyVersion, User
from clans.simulation import Command, SimulationError, transition


@pytest.fixture
def sim(engine, identities, headers, request):
    signer_count, threshold = getattr(request, "param", (3, 2))
    with Session(engine) as session:
        policy = session.scalar(
            select(PolicyVersion).where(PolicyVersion.clan_id == identities["clan_id"])
        )
        policy.signer_threshold = threshold
        for number in range(4, signer_count + 1):
            token = secrets.token_urlsafe(32)
            user = User(
                display_name=f"Test Signer {number}",
                is_test_user=True,
                demo_token_hash=hashlib.sha256(token.encode()).hexdigest(),
            )
            session.add(user)
            session.flush()
            session.add(
                Membership(
                    clan_id=identities["clan_id"],
                    user_id=user.id,
                    is_signer=True,
                )
            )
            identities["users"][f"signer_{number}"] = {"id": user.id, "bearer_token": token}
        session.commit()
    with TestClient(
        create_app(Settings(demo_auth_enabled=True, simulation_enabled=True), engine)
    ) as c:
        root = f"/api/v1/clans/{identities['clan_id']}/simulations"
        result = c.post(root, headers={**headers(), "Idempotency-Key": "start"}, json={})
        assert result.status_code == 201
        run = result.json()
        path = root + "/" + run["id"]

        def command(action, persona="chair", key=None, expected=200, **fields):
            response = c.post(
                path + "/commands",
                json={"action": action, **fields},
                headers={**headers(persona), "Idempotency-Key": key or str(uuid4())},
            )
            assert response.status_code == expected, response.text
            return response.json()

        yield c, path, command, run


def grant_ready(command, amount=5000, currency="BTC"):
    command("contribute", amount_sats=10000)
    run = command(
        "request_grant",
        "beneficiary",
        amount_sats=amount,
        purpose="Working capital",
        obligation_currency=currency,
        kes_minor_per_1000_sats=2500,
    )
    gid = next(iter(run["state"]["grants"]))
    for voter in ["chair", "treasurer", "member"]:
        command("vote", voter, grant_id=gid, choice="approve")
    command("accept_terms", "beneficiary", grant_id=gid)
    return gid


def authorize(command, gid, fee=10):
    run = command(
        "freeze_intent", grant_id=gid, destination="sim:beneficiary", fee_ceiling_sats=fee
    )
    intent = run["state"]["grants"][gid]["intent"]["sha256"]
    for signer in ["chair", "treasurer"]:
        command("approve_intent", signer, grant_id=gid, intent_sha256=intent)
    return intent


def issued(command, currency="BTC"):
    gid = grant_ready(command, currency=currency)
    intent = authorize(command, gid)
    command("execute", grant_id=gid, intent_sha256=intent, actual_fee_sats=2)
    return gid, intent


def assert_balanced(state):
    treasury = 0
    for entry in state["journal"]:
        assert sum(line["debit_sats"] for line in entry["lines"]) == sum(
            line["credit_sats"] for line in entry["lines"]
        )
        treasury += sum(
            line["debit_sats"] - line["credit_sats"]
            for line in entry["lines"]
            if line["account"] == "treasury"
        )
    assert treasury == state["balance_sats"]
    assert state["balance_sats"] == (
        state["contributed_sats"]
        + state["recovered_sats"]
        - state["disbursed_sats"]
        - state["fees_sats"]
    )
    assert state["available_sats"] == state["balance_sats"] - state["reserved_sats"]


def test_full_cycle_partial_otc_forgiveness_and_reuse(sim, identities):
    _, _, command, _ = sim
    gid, _ = issued(command)
    command(
        "repay",
        "beneficiary",
        grant_id=gid,
        amount_sats=1000,
        settlement_reference="sim:direct-one",
    )
    run = command(
        "repay",
        "beneficiary",
        grant_id=gid,
        amount_sats=2000,
        method="otc",
        remitter_user_id=identities["users"]["otc_merchant"]["id"],
        settlement_reference="sim:merchant-one",
    )
    grant = run["state"]["grants"][gid]
    assert grant["outstanding_minor"] == 2000
    assert grant["repayments"][1]["beneficiary_id"] == identities["users"]["beneficiary"]["id"]
    assert grant["repayments"][1]["remitter_id"] == identities["users"]["otc_merchant"]["id"]
    run = command(
        "propose_amendment", grant_id=gid, new_outstanding_minor=1500, reason="Group support"
    )
    aid = run["state"]["grants"][gid]["amendments"][0]["id"]
    for voter in ["chair", "treasurer", "member"]:
        run = command("vote_amendment", voter, grant_id=gid, amendment_id=aid, choice="approve")
    assert run["state"]["grants"][gid]["forgiven_minor"] == 500
    run = command("request_grant", "member", amount_sats=6000, purpose="Reuse recovered capital")
    second = next(g for g in run["state"]["grants"].values() if g["id"] != gid)
    assert second["amount_sats"] > 4998  # Without recovery, only 4,998 sats remained.
    for voter in ["chair", "treasurer", "secretary"]:
        command("vote", voter, grant_id=second["id"], choice="approve")
    command("accept_terms", "member", grant_id=second["id"])
    intent = authorize(command, second["id"])
    final = command("execute", grant_id=second["id"], intent_sha256=intent, actual_fee_sats=2)
    assert final["state"]["balance_sats"] == 1996
    assert final["state"]["recovered_sats"] == 3000
    assert final["state"]["disbursed_sats"] == 11000
    assert final["mode"] == "simulation" and not final["real_payments_enabled"]
    assert_balanced(final["state"])


def test_simulation_disabled_by_default(client, headers, identities):
    path = f"/api/v1/clans/{identities['clan_id']}/simulations"
    assert (
        client.post(path, headers={**headers(), "Idempotency-Key": "x"}, json={}).status_code == 503
    )


@pytest.mark.parametrize("sim", [(3, 2), (5, 3), (7, 4)], indirect=True)
def test_configurable_signer_rosters_require_their_selected_threshold(sim):
    _, _, command, original = sim
    threshold = original["state"]["policy_snapshot"]["signer_threshold"]
    count = sum(member["is_signer"] for member in original["state"]["roster_snapshot"])
    assert (count, threshold) in {(3, 2), (5, 3), (7, 4)}
    gid = grant_ready(command)
    run = command("freeze_intent", grant_id=gid, destination="sim:beneficiary")
    intent = run["state"]["grants"][gid]["intent"]["sha256"]
    signers = ["chair", "treasurer", "secretary"] + [
        f"signer_{number}" for number in range(4, count + 1)
    ]
    # Use the added signers too, rather than proving only the original three work.
    signers.reverse()
    for signer in signers[: threshold - 1]:
        command("approve_intent", signer, grant_id=gid, intent_sha256=intent)
    blocked = command("execute", grant_id=gid, intent_sha256=intent, expected=409)
    assert blocked["error"]["code"] == "insufficient_approvals"
    command("approve_intent", signers[threshold - 1], grant_id=gid, intent_sha256=intent)
    run = command("execute", grant_id=gid, intent_sha256=intent, actual_fee_sats=2)
    assert run["state"]["balance_sats"] == 4998
    assert_balanced(run["state"])


def test_creation_and_command_idempotency(sim, headers):
    client, path, command, original = sim
    duplicate = client.post(
        path.rsplit("/", 1)[0], headers={**headers(), "Idempotency-Key": "start"}, json={}
    )
    assert duplicate.json() == original
    first = command("contribute", amount_sats=1000, key="same")
    retry = command("contribute", amount_sats=1000, key="same")
    assert first == retry
    assert client.get(path, headers=headers()).json()["state"]["balance_sats"] == 1000
    conflict = command("contribute", amount_sats=2000, key="same", expected=409)
    assert conflict["error"]["code"] == "idempotency_conflict"


def test_same_key_is_scoped_to_actor(sim):
    _, _, command, _ = sim
    command("contribute", amount_sats=1000, key="same")
    run = command("contribute", "member", amount_sats=1000, key="same")
    assert run["state"]["balance_sats"] == 2000


def test_outsider_cannot_read_or_mutate_simulation(sim, headers):
    client, path, _, _ = sim
    assert client.get(path, headers=headers("otc_merchant")).status_code == 404
    response = client.post(
        path + "/commands",
        headers={**headers("otc_merchant"), "Idempotency-Key": "x"},
        json={"action": "contribute", "amount_sats": 1000},
    )
    assert response.status_code == 404


def test_fake_claim_of_live_settlement_rejected(sim, headers):
    client, path, _, _ = sim
    response = client.post(
        path + "/commands",
        headers={**headers(), "Idempotency-Key": "x"},
        json={"action": "contribute", "amount_sats": 2568, "provider": "btcpay"},
    )
    assert response.status_code == 422


@pytest.mark.parametrize("amount", [0, -1, "100", True, 2100000000000001])
def test_rejects_invalid_money_without_changes(sim, headers, amount):
    client, path, _, original = sim
    response = client.post(
        path + "/commands",
        headers={**headers(), "Idempotency-Key": "x"},
        json={"action": "contribute", "amount_sats": amount},
    )
    assert response.status_code == 422
    assert client.get(path, headers=headers()).json() == original


def test_beneficiary_and_duplicate_votes_rejected(sim):
    _, _, command, _ = sim
    run = command("request_grant", "beneficiary", amount_sats=1000, purpose="Test")
    gid = next(iter(run["state"]["grants"]))
    result = command("vote", "beneficiary", grant_id=gid, choice="approve", expected=403)
    assert result["error"]["code"] == "conflict_of_interest"
    command("vote", grant_id=gid, choice="approve")
    assert (
        command("vote", grant_id=gid, choice="approve", expected=409)["error"]["code"]
        == "duplicate_vote"
    )


def test_vote_is_distinct_from_approval_and_payout(sim):
    _, _, command, _ = sim
    gid = grant_ready(command)
    run = command("freeze_intent", grant_id=gid, destination="sim:recipient", fee_ceiling_sats=10)
    intent = run["state"]["grants"][gid]["intent"]["sha256"]
    command("approve_intent", grant_id=gid, intent_sha256=intent)
    result = command("execute", grant_id=gid, intent_sha256=intent, expected=409)
    assert result["error"]["code"] == "insufficient_approvals"


def test_destination_mutation_invalidates_old_approvals_and_does_not_double_reserve(sim):
    _, _, command, _ = sim
    gid = grant_ready(command)
    old = authorize(command, gid)
    run = command("freeze_intent", grant_id=gid, destination="sim:changed", fee_ceiling_sats=10)
    assert run["state"]["reserved_sats"] == 5010
    assert run["state"]["grants"][gid]["approvals"] == []
    result = command("execute", grant_id=gid, intent_sha256=old, expected=409)
    assert result["error"]["code"] == "intent_mismatch"


def test_fee_ceiling_double_execution_and_expired_intent(sim, identities):
    _, _, command, _ = sim
    gid = grant_ready(command)
    intent = authorize(command, gid)
    assert (
        command("execute", grant_id=gid, intent_sha256=intent, actual_fee_sats=11, expected=409)[
            "error"
        ]["code"]
        == "fee_ceiling_exceeded"
    )
    run = command("approve_intent", "secretary", grant_id=gid, intent_sha256=intent)
    state = run["state"]
    expired = datetime.fromisoformat(state["grants"][gid]["intent"]["expires_at"]) + timedelta(
        seconds=1
    )
    actor = identities["users"]["chair"]["id"]
    members = {r["user_id"] for r in state["roster_snapshot"]}
    signers = {r["user_id"] for r in state["roster_snapshot"] if r["is_signer"]}
    with pytest.raises(SimulationError, match="Intent expired"):
        transition(
            state,
            TypeAdapter(Command).validate_python(
                {"action": "execute", "grant_id": gid, "intent_sha256": intent}
            ),
            actor,
            members,
            signers,
            set(),
            now=expired,
        )
    command("execute", grant_id=gid, intent_sha256=intent)
    assert (
        command("execute", grant_id=gid, intent_sha256=intent, expected=409)["error"]["code"]
        == "invalid_state"
    )


def test_cancel_releases_reserved_funds(sim):
    _, _, command, _ = sim
    gid = grant_ready(command)
    authorize(command, gid)
    run = command("cancel_intent", grant_id=gid)
    assert run["state"]["reserved_sats"] == 0
    assert run["state"]["available_sats"] == 10000
    assert run["state"]["grants"][gid]["approvals"] == []


def test_no_overdraft_from_overlapping_grants(sim):
    _, _, command, _ = sim
    gid = grant_ready(command, amount=7000)
    authorize(command, gid)
    run = command("request_grant", "member", amount_sats=4000, purpose="Second")
    second = next(g for g in run["state"]["grants"] if g != gid)
    for voter in ["chair", "treasurer", "secretary"]:
        command("vote", voter, grant_id=second, choice="approve")
    command("accept_terms", "member", grant_id=second)
    assert (
        command("freeze_intent", grant_id=second, destination="sim:second", expected=409)["error"][
            "code"
        ]
        == "insufficient_funds"
    )


def test_removed_signer_invalidates_execution_quorum(sim, engine, identities):
    _, _, command, _ = sim
    gid = grant_ready(command)
    intent = authorize(command, gid)
    with Session(engine) as session:
        member = session.scalar(
            select(Membership).where(Membership.user_id == identities["users"]["treasurer"]["id"])
        )
        member.is_signer = False
        session.commit()
    assert (
        command("execute", grant_id=gid, intent_sha256=intent, expected=409)["error"]["code"]
        == "insufficient_approvals"
    )


def test_removed_voter_invalidates_member_quorum(sim, engine, identities):
    _, _, command, _ = sim
    gid = grant_ready(command)
    intent = authorize(command, gid)
    with Session(engine) as session:
        member = session.scalar(
            select(Membership).where(Membership.user_id == identities["users"]["member"]["id"])
        )
        member.active = False
        session.commit()
    assert (
        command("execute", grant_id=gid, intent_sha256=intent, expected=409)["error"]["code"]
        == "quorum_lost"
    )


def test_policy_snapshot_survives_later_policy_edit(sim, engine, identities):
    _, _, command, original = sim
    with Session(engine) as session:
        policy = session.scalar(
            select(PolicyVersion).where(PolicyVersion.clan_id == identities["clan_id"])
        )
        policy.signer_threshold = 1
        session.commit()
    run = command("contribute", amount_sats=1000)
    assert run["state"]["policy_snapshot"] == original["state"]["policy_snapshot"]
    assert run["state"]["policy_snapshot"]["signer_threshold"] == 2


def test_repayment_cannot_duplicate_or_overpay(sim):
    _, _, command, _ = sim
    gid, _ = issued(command)
    command(
        "repay", "beneficiary", grant_id=gid, amount_sats=1000, settlement_reference="sim:first"
    )
    assert (
        command(
            "repay",
            "beneficiary",
            grant_id=gid,
            amount_sats=1000,
            settlement_reference="sim:first",
            expected=409,
        )["error"]["code"]
        == "duplicate_settlement"
    )
    assert (
        command(
            "repay",
            "beneficiary",
            grant_id=gid,
            amount_sats=5000,
            settlement_reference="sim:other",
            expected=422,
        )["error"]["code"]
        == "invalid_recovery_credit"
    )


def test_kes_obligation_is_separate_from_sats(sim):
    _, _, command, _ = sim
    gid, _ = issued(command, currency="KES")
    run = command(
        "repay",
        "beneficiary",
        grant_id=gid,
        amount_sats=1000,
        settlement_reference="sim:kes-credit",
    )
    grant = run["state"]["grants"][gid]
    assert grant["principal_minor"] == 12500  # KES 125 at the explicit mock valuation.
    assert grant["recovered_minor"] == 2500
    assert grant["outstanding_minor"] == 10000
    assert grant["recovered_sats"] == 1000
    assert_balanced(run["state"])


def test_invalid_otc_remitter_never_creates_credit(sim):
    _, _, command, _ = sim
    gid, _ = issued(command)
    response = command(
        "repay",
        "beneficiary",
        grant_id=gid,
        amount_sats=1000,
        method="otc",
        remitter_user_id="not-a-user",
        settlement_reference="sim:fake",
        expected=422,
    )
    assert response["error"]["code"] == "invalid_remitter"


def test_rejected_proposal_cannot_be_paid(sim):
    _, _, command, _ = sim
    run = command("request_grant", "beneficiary", amount_sats=1000, purpose="Test")
    gid = next(iter(run["state"]["grants"]))
    for voter in ["chair", "treasurer", "secretary", "member"]:
        run = command("vote", voter, grant_id=gid, choice="reject")
    assert run["state"]["grants"][gid]["status"] == "rejected"
    assert (
        command("accept_terms", "beneficiary", grant_id=gid, expected=409)["error"]["code"]
        == "invalid_state"
    )
