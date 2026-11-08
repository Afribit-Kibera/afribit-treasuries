"""Clone only the synthetic simulation state, preserving the owner's PWA preview."""

import copy
import json
from pathlib import Path

from clans.db import make_engine
from clans.simulation import SimulationRun
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    fixture = json.loads(
        (ROOT / ".local/pwa-identities.json").read_text(encoding="utf-8")
    )
    assert (
        fixture["is_test_fixture"] is True and fixture["payment_mode"] == "simulation"
    )
    engine = make_engine(
        "sqlite+pysqlite:///" + (ROOT / ".local/pwa-preview.db").as_posix()
    )
    with Session(engine) as session:
        original = session.get(SimulationRun, fixture["run_id"])
        assert original is not None
        qa = SimulationRun(
            clan_id=original.clan_id,
            created_by=original.created_by,
            state=copy.deepcopy(original.state),
        )
        session.add(qa)
        session.commit()
        report = {
            "url": "http://127.0.0.1:5177/?demoRun=" + qa.id,
            "simulation_only": True,
        }
    (ROOT / ".local/pwa-qa-session.json").write_text(
        json.dumps(report), encoding="utf-8"
    )
    engine.dispose()
    print(json.dumps(report))


if __name__ == "__main__":
    main()
