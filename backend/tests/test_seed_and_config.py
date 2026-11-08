import hashlib

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from clans.config import Settings
from clans.models import Membership, PolicyVersion, User
from clans.seed import seed_demo


def test_database_contains_token_hashes_not_plaintext(engine, identities):
    with Session(engine) as session:
        user = session.get(User, identities["users"]["chair"]["id"])
        raw = identities["users"]["chair"]["bearer_token"]
        assert user.demo_token_hash == hashlib.sha256(raw.encode()).hexdigest()
        assert user.demo_token_hash != raw


def test_reseeding_preserves_existing_users(engine, identities):
    with Session(engine) as session, pytest.raises(ValueError, match="empty database"):
        seed_demo(session)
    with Session(engine) as session:
        assert len(session.scalars(select(User)).all()) == 6


def test_database_rejects_duplicate_membership(engine, identities):
    with Session(engine) as session:
        session.add(
            Membership(clan_id=identities["clan_id"], user_id=identities["users"]["chair"]["id"])
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_database_rejects_invalid_policy_threshold(engine, identities):
    with Session(engine) as session:
        session.add(
            PolicyVersion(
                clan_id=identities["clan_id"], version=2, member_vote_quorum=0, signer_threshold=2
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


@pytest.mark.parametrize(
    "url",
    [
        "http://btcpay.example",
        "https://user:password@btcpay.example",
        "https://btcpay.example?key=x",
        "https://btcpay.example/unexpected-path",
        "https://btcpay.example#fragment",
    ],
)
def test_config_rejects_credential_bearing_or_non_origin_provider_urls(url):
    with pytest.raises(ValidationError):
        Settings(btcpay_url=url)


def test_settings_repr_hides_secrets():
    settings = Settings(btcpay_api_key="sensitive-test-value")
    assert "sensitive-test-value" not in repr(settings)


def test_live_payment_mode_cannot_be_enabled_by_configuration():
    with pytest.raises(ValidationError):
        Settings(payment_mode="mainnet")
