"""Exercise ASGI stream boundaries and real loopback Uvicorn/Caddy chunking."""

import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from test_live_app import live as live

from clans.request_limits import RequestBodyLimit


@pytest.mark.parametrize(
    "length,status", [(None, 200), (b"65536", 200), (b"-1", 400), (b"oops", 400), (b"65537", 413)]
)
def test_stream_limits_and_malformed_lengths(length, status):
    async def exercise():
        called, sent = [], []

        async def app(scope, receive, send):
            called.append(await receive())
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        events = iter(
            [
                {"type": "http.request", "body": b" " * 32768, "more_body": True},
                {"type": "http.request", "body": b" " * 32768, "more_body": False},
            ]
        )

        async def receive():
            return next(events)

        async def send(event):
            sent.append(event)

        await RequestBodyLimit(app)(
            {"type": "http", "headers": [(b"content-length", length)] if length else []},
            receive,
            send,
        )
        assert sent[0]["status"] == status
        assert bool(called) == (status == 200)
        if called:
            assert len(called[0]["body"]) == 65536

    asyncio.run(exercise())


def port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.mark.skipif(
    os.name != "posix" or not shutil.which("caddy"), reason="Requires isolated Linux Caddy binary"
)
def test_real_chunked_requests_through_uvicorn_and_caddy(live, tmp_path):
    api_port, edge_port = port(), port()
    settings = live.state.security.settings
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLANS_")}
    env.update(
        CLANS_ENVIRONMENT="test",
        CLANS_DATABASE_URL=settings.database_url.get_secret_value(),
        CLANS_SESSION_SECRET=settings.session_secret.get_secret_value(),
        CLANS_PUBLIC_ORIGIN=settings.public_origin,
        CLANS_RP_ID=settings.rp_id,
        HOME=str(tmp_path),
    )
    config = tmp_path / "Caddyfile"
    config.write_text(
        "{\n admin off\n auto_https off\n}\nhttp://127.0.0.1:"
        + str(edge_port)
        + " {\n request_body {\n max_size 64KB\n }\n reverse_proxy 127.0.0.1:"
        + str(api_port)
        + "\n}\n",
        encoding="utf-8",
    )
    repo = Path(__file__).resolve().parents[2]
    assert "max_size 64KB" in (repo / "ops/Caddyfile.clans").read_text(encoding="utf-8")
    processes = []
    try:
        processes.append(
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "clans.live_app:create_app",
                    "--factory",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(api_port),
                    "--no-access-log",
                ],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        )
        processes.append(
            subprocess.Popen(
                ["caddy", "run", "--config", str(config), "--adapter", "caddyfile"],
                env=env,
                cwd=tmp_path,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        )
        for address in [api_port, edge_port]:
            origin = f"http://127.0.0.1:{address}"
            for _ in range(50):
                try:
                    if httpx.get(origin + "/api/session", timeout=1).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            else:
                pytest.fail("Isolated request-limit server failed startup")
            response = httpx.post(
                origin + "/api/auth/register/options",
                content=iter([b"{}", b" " * 131072]),
                headers={"Content-Type": "application/json", "Origin": settings.public_origin},
                timeout=5,
            )
            assert response.status_code == 413
            small = httpx.post(
                origin + "/api/auth/register/options",
                content=iter([json.dumps({}).encode()]),
                headers={"Content-Type": "application/json", "Origin": settings.public_origin},
                timeout=5,
            )
            assert small.status_code == 422  # Reached validation, not rejected by byte guard.
    finally:
        for process in processes:
            process.terminate()
            process.wait(timeout=10)
