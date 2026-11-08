"""Keep local snapshots working while the owner defers offsite backup setup.

Run as PostgreSQL's OS account over its local socket. No application, database
owner or provider credentials are passed to the web service or this script.
Local snapshots do not protect against losing the server.
"""

import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path


def main():
    os.umask(0o077)
    directory = Path("/var/lib/afribit-clans-local-backup")
    target = directory / (datetime.now(UTC).strftime("clans-%Y%m%d-%H%M%S") + ".dump")
    temporary = target.with_suffix(".partial")
    try:
        subprocess.run(
            [
                "/usr/bin/pg_dump",
                "--format=custom",
                "--dbname=afribit_clans",
                "--file=" + str(temporary),
            ],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["/usr/bin/pg_restore", "--list", str(temporary)],
            check=True,
            capture_output=True,
        )
        temporary.replace(target)
    except (OSError, subprocess.CalledProcessError):
        temporary.unlink(missing_ok=True)
        raise SystemExit(
            "Local Clans snapshot failed; existing snapshots were kept"
        ) from None
    for path in sorted(directory.glob("clans-*.dump"), reverse=True)[14:]:
        path.unlink()
    print(
        "Local Clans snapshot created and archive checked. Offsite backup remains deferred."
    )


if __name__ == "__main__":
    main()
