import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from clans.api import create_app
from clans.config import Settings
from clans.db import Base, make_engine
from clans.seed import seed_demo


@pytest.fixture
def engine():
    db = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(db)
    yield db
    db.dispose()


@pytest.fixture
def identities(engine):
    with Session(engine) as session:
        result = seed_demo(session)
        session.commit()
    return result


@pytest.fixture
def client(engine, identities):
    settings = Settings(demo_auth_enabled=True)
    with TestClient(create_app(settings, engine)) as http:
        yield http


@pytest.fixture
def headers(identities):
    def for_persona(persona="chair"):
        return {"Authorization": "Bearer " + identities["users"][persona]["bearer_token"]}

    return for_persona
