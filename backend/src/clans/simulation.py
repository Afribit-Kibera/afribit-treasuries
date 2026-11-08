"""Deterministic demo governance and journals. No network or wallet execution code."""

import copy
import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from sqlalchemy import JSON, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from clans.db import Base
from clans.models import new_id, now_iso

MAX_SATS = 2_100_000_000_000_000
Amount = Annotated[int, Field(strict=True, gt=0, le=MAX_SATS)]
Nonnegative = Annotated[int, Field(strict=True, ge=0, le=MAX_SATS)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class SimulationRun(Base):
    __tablename__ = "simulation_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    clan_id: Mapped[str] = mapped_column(ForeignKey("clans.id"), index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[str] = mapped_column(String(40), default=now_iso)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[dict] = mapped_column(JSON)


class SimulationCommandRecord(Base):
    __tablename__ = "simulation_commands"
    __table_args__ = (UniqueConstraint("run_id", "actor_id", "idempotency_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("simulation_runs.id"), index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    idempotency_key: Mapped[str] = mapped_column(String(120))
    request_sha256: Mapped[str] = mapped_column(String(64))
    occurred_at: Mapped[str] = mapped_column(String(40), default=now_iso)
    response: Mapped[dict] = mapped_column(JSON)


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class StartSimulation(StrictInput):
    name: Text = "Circular grant demonstration"


class Contribution(StrictInput):
    action: Literal["contribute"]
    amount_sats: Amount


class RequestGrant(StrictInput):
    action: Literal["request_grant"]
    amount_sats: Amount
    purpose: Text
    obligation_currency: Literal["BTC", "KES"] = "BTC"
    # Only a simulation valuation fixture: KES minor units credited per 1,000 sats.
    kes_minor_per_1000_sats: Annotated[int, Field(strict=True, gt=0, le=100_000_000)] = 100


class GrantRef(StrictInput):
    grant_id: Annotated[str, StringConstraints(min_length=1, max_length=36)]


class Vote(GrantRef):
    action: Literal["vote"]
    choice: Literal["approve", "reject", "abstain"]


class AcceptTerms(GrantRef):
    action: Literal["accept_terms"]


class FreezeIntent(GrantRef):
    action: Literal["freeze_intent"]
    destination: Annotated[str, StringConstraints(pattern=r"^sim:[A-Za-z0-9_-]{1,100}$")]
    fee_ceiling_sats: Nonnegative = 10
    expires_in_seconds: Annotated[int, Field(strict=True, ge=1, le=3600)] = 300


class ApproveIntent(GrantRef):
    action: Literal["approve_intent"]
    intent_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class CancelIntent(GrantRef):
    action: Literal["cancel_intent"]


class Execute(GrantRef):
    action: Literal["execute"]
    intent_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    actual_fee_sats: Nonnegative = 0


class Repay(GrantRef):
    action: Literal["repay"]
    amount_sats: Amount
    method: Literal["lightning", "otc"] = "lightning"
    # OTC remitter is a synthetic user, not a clan member or the credited beneficiary.
    remitter_user_id: str | None = Field(default=None, max_length=36)
    settlement_reference: Annotated[str, StringConstraints(pattern=r"^sim:[A-Za-z0-9_-]{1,100}$")]

    @model_validator(mode="after")
    def validate_remitter(self):
        if self.method == "otc" and not self.remitter_user_id:
            raise ValueError("OTC requires a remitter")
        if self.method == "lightning" and self.remitter_user_id is not None:
            raise ValueError("Direct repayment uses the beneficiary as remitter")
        return self


class ProposeAmendment(GrantRef):
    action: Literal["propose_amendment"]
    new_outstanding_minor: Nonnegative
    reason: Text


class VoteAmendment(GrantRef):
    action: Literal["vote_amendment"]
    amendment_id: str = Field(min_length=1, max_length=36)
    choice: Literal["approve", "reject", "abstain"]


Command = Annotated[
    Contribution
    | RequestGrant
    | Vote
    | AcceptTerms
    | FreezeIntent
    | ApproveIntent
    | Execute
    | CancelIntent
    | Repay
    | ProposeAmendment
    | VoteAmendment,
    Field(discriminator="action"),
]


class SimulationView(BaseModel):
    id: str
    clan_id: str
    revision: int
    mode: Literal["simulation"] = "simulation"
    real_payments_enabled: Literal[False] = False
    state: dict


class SimulationError(Exception):
    def __init__(self, code: str, message: str, status: int = 409):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def digest(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def initial_state(name: str, policy: dict, roster: list[dict]) -> dict:
    return {
        "name": name,
        "policy_snapshot": policy,
        "roster_snapshot": roster,
        "balance_sats": 0,
        "reserved_sats": 0,
        "available_sats": 0,
        "contributed_sats": 0,
        "disbursed_sats": 0,
        "recovered_sats": 0,
        "fees_sats": 0,
        "grants": {},
        "journal": [],
        "events": [],
        "settlement_references": [],
        "valuation": "simulation_fixture_only",
    }


def require(condition: bool, code: str, message: str, status: int = 409) -> None:
    if not condition:
        raise SimulationError(code, message, status)


def transition(
    previous: dict,
    command: Command,
    actor_id: str,
    live_members: set[str],
    live_signers: set[str],
    synthetic_user_ids: set[str],
    *,
    now: datetime | None = None,
) -> dict:
    """Apply one atomic mock event; raise without mutating the input on failure."""
    state = copy.deepcopy(previous)
    now = now or datetime.now(UTC)
    timestamp = now.isoformat()
    policy = state["policy_snapshot"]
    roster = state["roster_snapshot"]
    members = {r["user_id"] for r in roster}
    signers = {r["user_id"] for r in roster if r["is_signer"]}
    require(
        actor_id in members & live_members,
        "not_eligible",
        "Active snapshot membership required",
        403,
    )

    def journal(kind: str, amount: int, debit: str, credit: str, grant_id: str | None = None):
        if amount:
            state["journal"].append(
                {
                    "id": str(uuid4()),
                    "kind": kind,
                    "grant_id": grant_id,
                    "at": timestamp,
                    "lines": [
                        {"account": debit, "debit_sats": amount, "credit_sats": 0},
                        {"account": credit, "debit_sats": 0, "credit_sats": amount},
                    ],
                }
            )

    grant = None
    if isinstance(command, GrantRef):
        grant = state["grants"].get(command.grant_id)
        require(grant is not None, "grant_not_found", "Grant not found in this simulation", 404)
    if command.action == "contribute":
        state["balance_sats"] += command.amount_sats
        state["contributed_sats"] += command.amount_sats
        journal("contribution", command.amount_sats, "treasury", "contributed_capital")
    elif command.action == "request_grant":
        eligible = members if policy["beneficiary_can_approve"] else members - {actor_id}
        eligible_signers = signers if policy["beneficiary_can_approve"] else signers - {actor_id}
        require(
            len(eligible & live_members) >= policy["member_vote_quorum"],
            "unreachable_quorum",
            "Not enough eligible voters for this grant",
        )
        require(
            len(eligible_signers & live_signers) >= policy["signer_threshold"],
            "unreachable_signers",
            "Not enough independent eligible signers",
        )
        target = command.amount_sats
        if command.obligation_currency == "KES":
            target = command.amount_sats * command.kes_minor_per_1000_sats // 1000
        require(target > 0, "amount_too_small", "Recovery target rounds to zero", 422)
        gid = str(uuid4())
        state["grants"][gid] = {
            "id": gid,
            "beneficiary_id": actor_id,
            "purpose": command.purpose,
            "amount_sats": command.amount_sats,
            "obligation_currency": command.obligation_currency,
            "obligation_unit": "sats" if command.obligation_currency == "BTC" else "KES_cents",
            "principal_minor": target,
            "outstanding_minor": target,
            "recovered_minor": 0,
            "forgiven_minor": 0,
            "recovered_sats": 0,
            "kes_minor_per_1000_sats": command.kes_minor_per_1000_sats,
            "status": "voting",
            "votes": {},
            "eligible_voter_ids": sorted(eligible),
            "eligible_signer_ids": sorted(eligible_signers),
            "intent": None,
            "approvals": [],
            "reserved_sats": 0,
            "repayments": [],
            "amendments": [],
            "disbursed_sats": 0,
        }
        grant = state["grants"][gid]
    elif command.action in {"vote", "vote_amendment"}:
        require(
            actor_id in grant["eligible_voter_ids"],
            "conflict_of_interest",
            "Beneficiary is not eligible to approve this grant",
            403,
        )
        if command.action == "vote":
            require(grant["status"] == "voting", "invalid_state", "Grant is not open for voting")
            target = grant
        else:
            target = next((a for a in grant["amendments"] if a["id"] == command.amendment_id), None)
            require(target is not None, "amendment_not_found", "Amendment not found", 404)
            require(target["status"] == "voting", "invalid_state", "Amendment is not open")
        require(actor_id not in target["votes"], "duplicate_vote", "Vote already recorded")
        target["votes"][actor_id] = command.choice
        # Count only members still active; a revoked member never supplies quorum.
        approvals = sum(
            v == "approve" and uid in live_members for uid, v in target["votes"].items()
        )
        if approvals >= policy["member_vote_quorum"]:
            target["status"] = "accepted"
            if command.action == "vote_amendment":
                require(
                    grant["outstanding_minor"] == target["previous_outstanding_minor"],
                    "stale_amendment",
                    "Recovery changed; propose a fresh amendment",
                )
                reduction = grant["outstanding_minor"] - target["new_outstanding_minor"]
                grant["outstanding_minor"] -= reduction
                grant["forgiven_minor"] += reduction
        elif len(target["votes"]) == len(grant["eligible_voter_ids"]):
            target["status"] = "rejected"
    elif command.action == "accept_terms":
        require(
            actor_id == grant["beneficiary_id"],
            "beneficiary_required",
            "Recipient must accept terms",
            403,
        )
        require(grant["status"] == "accepted", "invalid_state", "Member vote must pass first")
        grant["status"] = "terms_accepted"
    elif command.action == "freeze_intent":
        require(
            actor_id in grant["eligible_signer_ids"] and actor_id in live_signers,
            "signer_required",
            "An eligible active signer must prepare the payout",
            403,
        )
        require(
            grant["status"] in {"terms_accepted", "awaiting_signers", "authorized"},
            "invalid_state",
            "Recipient must accept terms before preparing payment",
        )
        total = grant["amount_sats"] + command.fee_ceiling_sats
        require(
            total <= state["balance_sats"] - state["reserved_sats"] + grant["reserved_sats"],
            "insufficient_funds",
            "Insufficient unreserved simulated funds",
        )
        state["reserved_sats"] += total - grant["reserved_sats"]
        grant["reserved_sats"] = total
        intent = {
            "grant_id": grant["id"],
            "beneficiary_id": grant["beneficiary_id"],
            "amount_sats": grant["amount_sats"],
            "fee_ceiling_sats": command.fee_ceiling_sats,
            "destination": command.destination,
            "policy_version": policy["version"],
            "expires_at": (now + timedelta(seconds=command.expires_in_seconds)).isoformat(),
            "nonce": str(uuid4()),
            "mode": "simulation",
        }
        grant["intent"] = {**intent, "sha256": digest(intent)}
        grant["approvals"] = []
        grant["status"] = "awaiting_signers"
    elif command.action == "cancel_intent":
        require(
            actor_id in grant["eligible_signer_ids"] and actor_id in live_signers,
            "signer_required",
            "An eligible active signer is required",
            403,
        )
        require(
            grant["status"] in {"awaiting_signers", "authorized"},
            "invalid_state",
            "No pending intent to cancel",
        )
        state["reserved_sats"] -= grant["reserved_sats"]
        grant["reserved_sats"] = 0
        grant["intent"] = None
        grant["approvals"] = []
        grant["status"] = "terms_accepted"
    elif command.action in {"approve_intent", "execute"}:
        intent = grant["intent"]
        require(
            intent is not None and command.intent_sha256 == intent["sha256"],
            "intent_mismatch",
            "Approval must match the current frozen intent",
        )
        require(
            now < datetime.fromisoformat(intent["expires_at"]), "intent_expired", "Intent expired"
        )
        require(
            grant["status"] in {"awaiting_signers", "authorized"},
            "invalid_state",
            "Payout is not awaiting authorization or execution",
        )
        active_approvals = set(grant["approvals"]) & live_signers & live_members
        if command.action == "approve_intent":
            require(
                actor_id in grant["eligible_signer_ids"] and actor_id in live_signers,
                "signer_required",
                "An eligible active signer is required",
                403,
            )
            require(
                actor_id not in grant["approvals"], "duplicate_approval", "Signer already approved"
            )
            grant["approvals"].append(actor_id)
            if len(active_approvals | {actor_id}) >= policy["signer_threshold"]:
                grant["status"] = "authorized"
        else:
            require(
                actor_id in live_signers and actor_id in grant["eligible_signer_ids"],
                "signer_required",
                "An eligible active signer must execute",
                403,
            )
            require(
                len(active_approvals) >= policy["signer_threshold"],
                "insufficient_approvals",
                "Required independent approvals are missing",
            )
            member_approvals = sum(
                choice == "approve" and uid in live_members
                for uid, choice in grant["votes"].items()
            )
            require(
                member_approvals >= policy["member_vote_quorum"],
                "quorum_lost",
                "The member decision no longer has active quorum",
            )
            require(
                command.actual_fee_sats <= intent["fee_ceiling_sats"],
                "fee_ceiling_exceeded",
                "Fee exceeds the approved ceiling",
            )
            require(
                grant["reserved_sats"] == grant["amount_sats"] + intent["fee_ceiling_sats"],
                "reservation_mismatch",
                "Payment reservation is inconsistent",
            )
            grant["status"] = "settled_simulated"
            grant["disbursed_sats"] = grant["amount_sats"]
            state["reserved_sats"] -= grant["reserved_sats"]
            grant["reserved_sats"] = 0
            state["balance_sats"] -= grant["amount_sats"] + command.actual_fee_sats
            state["disbursed_sats"] += grant["amount_sats"]
            state["fees_sats"] += command.actual_fee_sats
            journal(
                "disbursement", grant["amount_sats"], "grants_distributed", "treasury", grant["id"]
            )
            journal("routing_fee", command.actual_fee_sats, "fees", "treasury", grant["id"])
    elif command.action == "repay":
        require(
            actor_id == grant["beneficiary_id"],
            "beneficiary_required",
            "Beneficiary records this mock repayment",
            403,
        )
        require(grant["status"] == "settled_simulated", "invalid_state", "No issued grant to repay")
        require(
            command.settlement_reference not in state["settlement_references"],
            "duplicate_settlement",
            "Settlement reference already credited",
        )
        if command.method == "otc":
            require(
                command.remitter_user_id in synthetic_user_ids,
                "invalid_remitter",
                "OTC remitter must be an active synthetic user",
                422,
            )
            require(
                command.remitter_user_id != actor_id,
                "invalid_remitter",
                "OTC remitter must differ",
                422,
            )
        credit = command.amount_sats
        if grant["obligation_currency"] == "KES":
            credit = command.amount_sats * grant["kes_minor_per_1000_sats"] // 1000
        require(
            0 < credit <= grant["outstanding_minor"],
            "invalid_recovery_credit",
            "Repayment must reduce the remaining target without overpaying",
            422,
        )
        require(
            not any(a["status"] == "voting" for a in grant["amendments"]),
            "amendment_pending",
            "Resolve the simulated amendment before further repayment",
        )
        state["settlement_references"].append(command.settlement_reference)
        grant["outstanding_minor"] -= credit
        grant["recovered_minor"] += credit
        grant["recovered_sats"] += command.amount_sats
        state["balance_sats"] += command.amount_sats
        state["recovered_sats"] += command.amount_sats
        grant["repayments"].append(
            {
                "beneficiary_id": actor_id,
                "remitter_id": command.remitter_user_id or actor_id,
                "method": command.method,
                "sats": command.amount_sats,
                "credited_minor": credit,
                "reference": command.settlement_reference,
                "settled_at": timestamp,
                "settlement": "simulated_only",
            }
        )
        journal("repayment", command.amount_sats, "treasury", "grant_recovery", grant["id"])
    elif command.action == "propose_amendment":
        require(
            grant["status"] == "settled_simulated", "invalid_state", "Grant has not been issued"
        )
        require(
            command.new_outstanding_minor < grant["outstanding_minor"],
            "invalid_amendment",
            "This pilot supports reductions of the outstanding target",
            422,
        )
        require(
            not any(a["status"] == "voting" for a in grant["amendments"]),
            "amendment_pending",
            "An amendment is already open",
        )
        grant["amendments"].append(
            {
                "id": str(uuid4()),
                "new_outstanding_minor": command.new_outstanding_minor,
                "previous_outstanding_minor": grant["outstanding_minor"],
                "reason": command.reason,
                "proposer_id": actor_id,
                "status": "voting",
                "votes": {},
            }
        )
    state["available_sats"] = state["balance_sats"] - state["reserved_sats"]
    require(
        0 <= state["available_sats"] <= MAX_SATS and state["balance_sats"] <= MAX_SATS,
        "treasury_limit",
        "Simulated treasury bounds exceeded",
        422,
    )
    state["events"].append(
        {
            "action": command.action,
            "actor_id": actor_id,
            "at": timestamp,
            "grant_id": grant["id"] if grant else None,
        }
    )
    return state
