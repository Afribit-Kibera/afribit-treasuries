"""Seed an independent, synthetic PWA treasury; never use real provider funds."""

import json
import os
from pathlib import Path

from clans.api import create_app
from clans.config import Settings
from clans.db import Base, make_engine
from clans.models import Clan, User
from clans.seed import seed_demo
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    local = ROOT / ".local"
    local.mkdir(exist_ok=True)
    target = local / "pwa-identities.json"
    database = local / "pwa-preview.db"
    if target.exists():
        assert database.exists(), "Existing identity file has no matching database"
        print("Reusing PWA demo; existing data and fixture credentials preserved.")
        return
    if database.exists():
        raise SystemExit(
            "Existing PWA database preserved; reconcile missing identities before seeding"
        )
    engine = make_engine("sqlite+pysqlite:///" + database.as_posix())
    app = create_app(Settings(demo_auth_enabled=True, simulation_enabled=True), engine)
    Base.metadata.create_all(engine)
    names = {
        "chair": "Amara Njeri",
        "treasurer": "David Otieno",
        "secretary": "Amina Hassan",
        "beneficiary": "Grace Wanjiku",
        "member": "Samuel Mwangi",
        "otc_merchant": "Peter Kamau",
    }
    with Session(engine) as session:
        fixture = seed_demo(session)
        session.get(Clan, fixture["clan_id"]).name = "Soweto Traders"
        for key, user in fixture["users"].items():
            user["display_name"] = names[key]
            session.get(User, user["id"]).display_name = names[key]
        session.commit()
    with TestClient(app) as client:

        def headers(persona="chair", key="start"):
            return {
                "Authorization": "Bearer " + fixture["users"][persona]["bearer_token"],
                "Idempotency-Key": key,
            }

        root = f"/api/v1/clans/{fixture['clan_id']}/simulations"
        response = client.post(
            root, headers=headers(), json={"name": "Soweto Traders PWA demo"}
        )
        assert response.status_code == 201
        fixture["run_id"] = response.json()["id"]
        path = root + "/" + fixture["run_id"] + "/commands"
        index = 0

        def command(action, persona="chair", **fields):
            nonlocal index
            index += 1
            response = client.post(
                path,
                headers=headers(persona, str(index)),
                json={"action": action, **fields},
            )
            assert response.status_code == 200, (action, response.status_code)
            return response.json()

        command("contribute", amount_sats=2180000)
        run = command(
            "request_grant",
            "beneficiary",
            amount_sats=480000,
            purpose="Fresh stock for Grace's market stall",
            obligation_currency="KES",
            kes_minor_per_1000_sats=2500,
        )
        gid = next(iter(run["state"]["grants"]))
        for voter in ["chair", "treasurer", "member"]:
            command("vote", voter, grant_id=gid, choice="approve")
        command("accept_terms", "beneficiary", grant_id=gid)
        run = command(
            "freeze_intent", grant_id=gid, destination="sim:grace", fee_ceiling_sats=10
        )
        intent = run["state"]["grants"][gid]["intent"]["sha256"]
        for signer in ["chair", "treasurer"]:
            command("approve_intent", signer, grant_id=gid, intent_sha256=intent)
        command("execute", grant_id=gid, intent_sha256=intent, actual_fee_sats=0)
        run = command(
            "request_grant",
            "member",
            amount_sats=320000,
            purpose="Restocking Samuel's produce stall",
            obligation_currency="KES",
            kes_minor_per_1000_sats=2500,
        )
        pending = next(g for g in run["state"]["grants"] if g != gid)
        command("vote", "secretary", grant_id=pending, choice="approve")
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(fixture, stream, indent=2)
    engine.dispose()
    print(
        "Prepared independent Soweto Traders simulation: KES42,500 available; KES12,000 recovery; KES8,000 request. No real funds."
    )


if __name__ == "__main__":
    main()
