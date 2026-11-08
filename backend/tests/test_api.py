import hashlib
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from clans.api import create_app
from clans.config import Settings
from clans.models import AuditEvent, Clan, Membership, PolicyVersion, User
from clans.payments import BtcpayProbe, ProviderUnavailable


def test_health_distinguishes_simulation_from_execution(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": "0.1.0",
        "payment_mode": "simulation",
        "demo_auth_enabled": True,
        "payment_execution_enabled": False,
    }


def test_demo_auth_is_disabled_by_default(engine):
    with TestClient(create_app(Settings(demo_auth_enabled=False), engine)) as client:
        response = client.get("/api/v1/me")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "demo_auth_disabled"


@pytest.mark.parametrize("auth", [None, "Bearer wrong-token", "Basic abc", "Bearer"])
def test_auth_rejects_missing_invalid_and_wrong_scheme(client, auth):
    response = client.get("/api/v1/me", headers={"Authorization": auth} if auth else {})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_identity_does_not_disclose_token_or_hash(client, headers, identities):
    response = client.get("/api/v1/me", headers=headers())
    assert response.status_code == 200
    data = response.json()
    assert data["display_name"] == "Test Chair"
    token = identities["users"]["chair"]["bearer_token"]
    assert token not in response.text
    assert hashlib.sha256(token.encode()).hexdigest() not in response.text
    assert set(data) == {"id", "display_name", "is_test_user"}


@pytest.mark.parametrize("attribute", ["active", "is_test_user"])
def test_inactive_or_real_user_cannot_use_demo_auth(client, engine, identities, headers, attribute):
    with Session(engine) as session:
        user = session.get(User, identities["users"]["chair"]["id"])
        setattr(user, attribute, False)
        session.commit()
    assert client.get("/api/v1/me", headers=headers()).status_code == 401


def test_seed_matches_pilot_and_otc_is_outside_clan(client, headers, identities):
    clan_id = identities["clan_id"]
    response = client.get(f"/api/v1/clans/{clan_id}", headers=headers("beneficiary"))
    assert response.status_code == 200
    clan = response.json()
    assert clan["member_count"] == 5
    assert clan["signer_count"] == 3
    assert clan["policy"]["signer_threshold"] == 2
    assert clan["policy"]["member_vote_quorum"] == 3
    assert clan["policy"]["beneficiary_can_approve"] is False
    assert clan["governance_ready"] is True
    assert client.get("/api/v1/clans", headers=headers("otc_merchant")).json() == []


@pytest.mark.parametrize("suffix", ["", "/members"])
def test_nonmember_cannot_discover_clan_or_roster(client, headers, identities, suffix):
    existing = client.get(
        f"/api/v1/clans/{identities['clan_id']}{suffix}", headers=headers("otc_merchant")
    )
    missing = client.get(f"/api/v1/clans/not-a-clan{suffix}", headers=headers("otc_merchant"))
    assert existing.status_code == missing.status_code == 404
    assert existing.json() == missing.json()


def test_removed_member_loses_clan_access(client, headers, engine, identities):
    with Session(engine) as session:
        member = session.scalar(
            select(Membership).where(Membership.user_id == identities["users"]["member"]["id"])
        )
        member.active = False
        session.commit()
    assert client.get("/api/v1/clans", headers=headers("member")).json() == []
    response = client.get(f"/api/v1/clans/{identities['clan_id']}", headers=headers("member"))
    assert response.status_code == 404


def test_roster_excludes_removed_and_inactive_users(client, headers, engine, identities):
    with Session(engine) as session:
        user = session.get(User, identities["users"]["secretary"]["id"])
        user.active = False
        session.commit()
    response = client.get(f"/api/v1/clans/{identities['clan_id']}/members", headers=headers())
    assert len(response.json()) == 4
    clan = client.get(f"/api/v1/clans/{identities['clan_id']}", headers=headers()).json()
    assert clan["member_count"] == 4
    assert clan["signer_count"] == 2


def test_create_clan_is_persistent_audited_and_does_not_self_appoint_signer(
    client, headers, engine, identities
):
    with Session(engine) as session:
        session.scalar(
            select(Membership).where(Membership.user_id == identities["users"]["chair"]["id"])
        ).active = False
        session.commit()
    response = client.post(
        "/api/v1/clans",
        headers=headers(),
        json={
            "name": "  Another Test Clan  ",
            "policy": {"currency": "BTC", "member_vote_quorum": 1, "signer_threshold": 2},
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Another Test Clan"
    assert data["member_count"] == 1
    assert data["signer_count"] == 0
    assert data["governance_ready"] is False
    assert data["policy"]["version"] == 1
    assert data["policy"]["currency"] == "BTC"
    assert client.get(f"/api/v1/clans/{data['id']}", headers=headers()).json() == data
    with Session(engine) as session:
        assert session.get(Clan, data["id"]) is not None
        member = session.scalar(select(Membership).where(Membership.clan_id == data["id"]))
        assert member.role == "organizer"
        assert member.is_signer is False
        event = session.scalar(select(AuditEvent).where(AuditEvent.clan_id == data["id"]))
        assert event.event_type == "clan.created"
        assert event.actor_id == identities["users"]["chair"]["id"]


def test_create_clan_succeeds_while_btcpay_is_unavailable(
    client, headers, monkeypatch, engine, identities
):
    with Session(engine) as session:
        session.scalar(
            select(Membership).where(Membership.user_id == identities["users"]["chair"]["id"])
        ).active = False
        session.commit()

    def unavailable(_self):
        raise ProviderUnavailable("Test provider offline")

    monkeypatch.setattr(BtcpayProbe, "health", unavailable)
    assert client.get("/api/v1/system/btcpay/health", headers=headers()).status_code == 503
    response = client.post(
        "/api/v1/clans",
        headers=headers(),
        json={"name": "Unfunded new clan", "policy": {"signer_threshold": 4}},
    )
    assert response.status_code == 201
    clan = response.json()
    assert clan["policy"]["signer_threshold"] == 4
    assert clan["signer_count"] == 0 and clan["governance_ready"] is False
    assert client.get(f"/api/v1/clans/{clan['id']}", headers=headers()).status_code == 200


@pytest.mark.parametrize(
    "body",
    [
        {"name": " "},
        {"name": "x" * 101},
        {"name": "Test", "is_signer": True},
        {"name": "Test", "policy": {"currency": "USD"}},
        {"name": "Test", "policy": {"signer_threshold": 0}},
        {"name": "Test", "policy": {"member_vote_quorum": -1}},
        {"name": "Test", "policy": {"signer_threshold": "2"}},
        {"name": "Test", "policy": {"signer_threshold": True}},
        {"name": "Test", "policy": {"unknown_rule": True}},
    ],
)
def test_invalid_policy_never_partially_creates_records(client, headers, engine, body):
    with Session(engine) as session:
        before = tuple(
            session.scalar(select(func.count()).select_from(model))
            for model in [Clan, Membership, PolicyVersion, AuditEvent]
        )
    response = client.post("/api/v1/clans", headers=headers(), json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    with Session(engine) as session:
        after = tuple(
            session.scalar(select(func.count()).select_from(model))
            for model in [Clan, Membership, PolicyVersion, AuditEvent]
        )
    assert after == before


def test_pagination_and_bounded_page_size(client, headers, identities):
    path = f"/api/v1/clans/{identities['clan_id']}/members"
    page1 = client.get(path, params={"limit": 2}, headers=headers()).json()
    page2 = client.get(path, params={"limit": 2, "offset": 2}, headers=headers()).json()
    assert len(page1) == len(page2) == 2
    assert {m["user"]["id"] for m in page1}.isdisjoint(m["user"]["id"] for m in page2)
    assert client.get(path, params={"limit": 101}, headers=headers()).status_code == 422


def test_openapi_describes_auth_and_exposes_no_payment_execution(client):
    schema = client.get("/openapi.json").json()
    assert schema["paths"]["/api/v1/me"]["get"]["security"] == [{"HTTPBearer": []}]
    assert not any(term in path for path in schema["paths"] for term in ["/pay", "/payout"])
    serialized = json.dumps(schema)
    assert "demo_token_hash" not in serialized
    assert "btcpay_api_key" not in serialized
