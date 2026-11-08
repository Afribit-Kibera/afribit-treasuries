"""Create disposable test identities. Raw tokens are written only to an ignored file."""

import argparse
import hashlib
import json
import os
import secrets
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from clans.config import Settings
from clans.db import Base, make_engine
from clans.models import AuditEvent, Clan, Membership, PolicyVersion, User

PERSONAS = [
    ("chair", "Test Chair", "chairperson", True),
    ("treasurer", "Test Treasurer", "treasurer", True),
    ("secretary", "Test Secretary", "secretary", True),
    ("beneficiary", "Test Beneficiary", "member", False),
    ("member", "Test Member", "member", False),
    ("otc_merchant", "Test OTC Merchant", None, False),
]


def seed_demo(session: Session) -> dict:
    if session.scalar(select(User.id).limit(1)) is not None:
        raise ValueError("Demo seeding requires an empty database; existing records were preserved")
    result: dict = {"is_test_fixture": True, "payment_mode": "simulation", "users": {}}
    users = []
    for key, name, role, signer in PERSONAS:
        token = secrets.token_urlsafe(32)
        user = User(
            display_name=name,
            is_test_user=True,
            demo_token_hash=hashlib.sha256(token.encode()).hexdigest(),
        )
        session.add(user)
        session.flush()
        users.append((key, user, role, signer))
        result["users"][key] = {"id": user.id, "bearer_token": token}
    clan = Clan(name="Afribit Test Clan", created_by=users[0][1].id)
    session.add(clan)
    session.flush()
    result["clan_id"] = clan.id
    for _key, user, role, signer in users:
        if role is not None:
            session.add(Membership(clan_id=clan.id, user_id=user.id, role=role, is_signer=signer))
    session.add(
        PolicyVersion(
            clan_id=clan.id,
            member_vote_quorum=3,
            signer_threshold=2,
            currency="KES",
            beneficiary_can_approve=False,
        )
    )
    session.add(
        AuditEvent(
            clan_id=clan.id,
            actor_id=users[0][1].id,
            event_type="test_fixture.created",
            payload={"members": 5, "signers": 3, "signer_threshold": 2},
        )
    )
    session.flush()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".local/demo-identities.json"))
    args = parser.parse_args()
    settings = Settings()
    if not settings.demo_auth_enabled:
        parser.error("Set CLANS_DEMO_AUTH_ENABLED=true for this local test operation")
    if not settings.database_url.get_secret_value().startswith("sqlite"):
        parser.error("This disposable seed command currently supports only local SQLite")
    # Keep fixture credentials under the ignored local directory.
    local_root = Path(".local").resolve()
    target = args.output.resolve()
    if not target.is_relative_to(local_root):
        parser.error("Fixture credentials must be saved under .local/")
    settings.prepare_local_directory()
    target.parent.mkdir(parents=True, exist_ok=True)
    engine = make_engine(settings.database_url.get_secret_value())
    Base.metadata.create_all(engine)
    # Exclusive creation protects any existing fixture credentials.
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out, Session(engine) as session:
            data = seed_demo(session)
            out.write(json.dumps(data, indent=2))
            out.flush()
            os.fsync(out.fileno())
            session.commit()
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    finally:
        engine.dispose()
    print("Seeded six synthetic users and one five-member clan. Credentials saved under .local/.")


if __name__ == "__main__":
    main()
