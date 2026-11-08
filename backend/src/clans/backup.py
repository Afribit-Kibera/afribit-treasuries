"""Dedicated backup account: stream encrypted dumps and require offsite upload.

Private decryption keys must NEVER be placed on the application/backup host.
The remote storage must provide independent immutable retention; SCP alone does not.
"""

import hashlib
import os
import re
import secrets
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from sqlalchemy.engine import make_url

from clans.backup_crypto import encrypt


def validate_target(value):
    if not re.fullmatch(r"[a-z_][a-z0-9_-]*@[a-z0-9][a-z0-9.-]*:/[A-Za-z0-9_./-]+", value):
        raise ValueError("Use a fixed user@host:/absolute/directory backup destination")
    if ".." in value.split(":", 1)[1].split("/"):
        raise ValueError("Parent traversal is not allowed")
    return value.rstrip("/")


def main():
    os.umask(0o077)
    try:
        recipient = serialization.load_pem_public_key(
            Path(os.environ["CLANS_BACKUP_PUBLIC_KEY_FILE"]).read_bytes()
        )
        target = validate_target(os.environ["CLANS_BACKUP_SSH_TARGET"])
        url = make_url(os.environ["CLANS_DATABASE_URL"])
        if url.drivername not in {"postgresql", "postgresql+psycopg"}:
            raise ValueError("Backups require PostgreSQL")
        directory = Path("/var/lib/afribit-clans-backup")
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        stem = "clans-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ-") + secrets.token_hex(4)
        archive, partial = directory / (stem + ".dump.enc"), directory / (stem + ".partial")
        env = {
            "PATH": "/usr/bin:/bin",
            "PGHOST": url.host or "127.0.0.1",
            "PGPORT": str(url.port or 5432),
            "PGUSER": url.username or "",
            "PGPASSWORD": url.password or "",
            "PGDATABASE": url.database or "",
        }
        with tempfile.TemporaryFile() as errors:
            process = subprocess.Popen(
                ["/usr/bin/pg_dump", "--format=custom", "--no-owner", "--no-acl"],
                env=env,
                stdout=subprocess.PIPE,
                stderr=errors,
            )
            try:
                with partial.open("xb") as output:
                    encrypt(process.stdout, output, recipient)
                    output.flush()
                    os.fsync(output.fileno())
                if process.wait(timeout=60) != 0:
                    raise RuntimeError("PostgreSQL dump failed")
                partial.replace(archive)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=10)
                if process.stdout:
                    process.stdout.close()
                partial.unlink(missing_ok=True)
        with archive.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        sidecar = archive.with_suffix(".sha256")
        sidecar.write_text(digest + "  " + archive.name + "\n", encoding="ascii")
        result = subprocess.run(
            [
                "/usr/bin/scp",
                "-q",
                "-o",
                "BatchMode=yes",
                "-o",
                "StrictHostKeyChecking=yes",
                "-o",
                "ConnectTimeout=15",
                str(archive),
                str(sidecar),
                target + "/",
            ],
            capture_output=True,
            timeout=180,
            check=False,
        )
        if result.returncode:
            raise RuntimeError("Encrypted offsite upload failed")
        # Retain local copies on failure; prune only after a successful upload.
        for obsolete in sorted(directory.glob("clans-*.dump.enc"))[:-14]:
            obsolete.unlink()
            obsolete.with_suffix(".sha256").unlink(missing_ok=True)
        print("Encrypted Clans backup uploaded:", archive.name, flush=True)
    except Exception:
        raise SystemExit(
            "Clans encrypted/offsite backup failed; operator attention required."
        ) from None


if __name__ == "__main__":
    main()
