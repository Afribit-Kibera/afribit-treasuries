"""Offline-only backup decryption; never restores a database or runs a payment worker.

Use on the trusted recovery machine with an unencrypted PEM private key in protected
offline storage. No private key or decrypted dump should be copied to the app host.
"""

import argparse
import os
from pathlib import Path

from clans.backup_crypto import decrypt
from cryptography.exceptions import InvalidTag, UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--private-key", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    partial = args.output.with_name(args.output.name + ".unauthenticated-partial")
    if args.output.exists() or partial.exists():
        raise SystemExit("Refusing to overwrite a recovery file")
    try:
        key = serialization.load_pem_private_key(
            args.private_key.read_bytes(), password=None
        )
        with args.archive.open("rb") as source, partial.open("xb") as destination:
            decrypt(source, destination, key)
            destination.flush()
            os.fsync(destination.fileno())
        # Link creates the final pathname only if it does not already exist.
        # No unauthenticated plaintext is published under the final filename.
        os.link(partial, args.output)
        print(
            "Backup authenticated and decrypted. Restore only into an isolated database."
        )
    except (OSError, ValueError, TypeError, KeyError, InvalidTag, UnsupportedAlgorithm):
        raise SystemExit(
            "Backup decryption failed; no authenticated output was published."
        ) from None
    finally:
        partial.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
