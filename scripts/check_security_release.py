"""Local release gate. Never connects to production or enables money movement.

PostgreSQL assurance is not implied by a SQLite run. --require-postgres refuses
to pass without isolated database and role-admin settings (see remediation guide).
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-postgres", action="store_true")
    args = parser.parse_args()
    environment = {k: v for k, v in os.environ.items() if not k.startswith("CLANS_")}
    if args.require_postgres:
        values = {}
        for name in ["CLANS_TEST_DATABASE_URL", "CLANS_TEST_ROLE_ADMIN_URL"]:
            value = os.environ.get(name, "")
            if not value:
                raise SystemExit(
                    "Isolated PostgreSQL database AND role-admin URLs are required"
                )
            url = make_url(value)
            if url.database != "afribit_clans_tests" or not url.drivername.startswith(
                "postgresql"
            ):
                raise SystemExit(
                    "Only the disposable afribit_clans_tests database is allowed"
                )
            values[name] = value
        a, b = [make_url(value) for value in values.values()]
        if (a.host, a.port) != (b.host, b.port):
            raise SystemExit(
                "Test and role-admin connections must identify the same server"
            )
        environment.update(values)
    environment.update(CLANS_RECEIVING_ENABLED="false", CLANS_PAYOUTS_ENABLED="false")
    commands = [
        ([sys.executable, "-m", "pytest", "--runxfail", "-ra"], ROOT / "backend"),
        ([sys.executable, "-m", "ruff", "check", "backend", "scripts"], ROOT),
        (
            [sys.executable, "-m", "ruff", "format", "--check", "backend", "scripts"],
            ROOT,
        ),
        (
            [
                sys.executable,
                str(ROOT / "scripts/export_openapi.py"),
                "--live",
                "--check",
            ],
            ROOT,
        ),
    ]
    for command, directory in commands:
        result = subprocess.run(command, cwd=directory, env=environment, check=False)
        if result.returncode:
            raise SystemExit(result.returncode)
    print(
        "Local checks passed; deployed infrastructure and custody sign-off remain separate."
    )


if __name__ == "__main__":
    main()
