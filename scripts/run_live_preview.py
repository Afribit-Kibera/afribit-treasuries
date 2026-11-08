"""Loopback-only development service with an independent, non-production database."""

import os
import secrets
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parents[1]
directory = ROOT / ".local" / "live-preview"
directory.mkdir(parents=True, exist_ok=True)
secret = directory / "session-secret"
if not secret.exists():
    secret.write_text(secrets.token_urlsafe(64), encoding="utf-8")
for name in list(os.environ):
    if name.startswith("CLANS_"):
        del os.environ[name]
os.environ.update(
    CLANS_ENVIRONMENT="development",
    CLANS_DATABASE_URL="sqlite:///" + (directory / "app.db").as_posix(),
    CLANS_SESSION_SECRET=secret.read_text(encoding="utf-8"),
    CLANS_PUBLIC_ORIGIN="http://localhost:8410",
    CLANS_RP_ID="localhost",
    CLANS_STATIC_DIRECTORY=str(ROOT / "frontend" / "dist"),
    CLANS_RECEIVING_ENABLED="false",
    CLANS_PAYOUTS_ENABLED="false",
)
from clans.migrate import main as migrate

migrate()
uvicorn.run(
    "clans.live_app:create_app",
    factory=True,
    host="127.0.0.1",
    port=8410,
    access_log=False,
)
