"""Offline key generation and signing of independently reviewed clan manifests.

Never run keygen/sign on the application or Lightning host. The private key is
encrypted with an interactive passphrase and never included in a manifest.
"""

import argparse
import getpass
import json
from pathlib import Path

from clans.live_security import b64
from clans.money_service import canonical_json
from clans.signer_trust import DOMAIN
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def write_new(path, data):
    with path.open("xb") as output:
        output.write(data)
    path.chmod(0o600)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    keygen = commands.add_parser("keygen")
    keygen.add_argument("--private-key", type=Path, required=True)
    keygen.add_argument("--public-key", type=Path, required=True)
    sign = commands.add_parser("sign")
    sign.add_argument("--private-key", type=Path, required=True)
    sign.add_argument("--draft", type=Path, required=True)
    sign.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "keygen":
        if args.private_key.exists() or args.public_key.exists():
            raise SystemExit("Refusing to replace an existing trust key")
        password = getpass.getpass(
            "New offline key passphrase (at least 16 characters): "
        )
        if len(password) < 16 or password != getpass.getpass("Repeat passphrase: "):
            raise SystemExit(
                "Passphrases must match and contain at least 16 characters"
            )
        key = Ed25519PrivateKey.generate()
        write_new(
            args.private_key,
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.BestAvailableEncryption(password.encode()),
            ),
        )
        write_new(
            args.public_key, (b64(key.public_key().public_bytes_raw()) + "\n").encode()
        )
        print(
            "Offline key created. Copy only its public key to the worker configuration."
        )
        return
    password = getpass.getpass("Offline key passphrase: ")
    key = serialization.load_pem_private_key(
        args.private_key.read_bytes(), password.encode()
    )
    if not isinstance(key, Ed25519PrivateKey):
        raise SystemExit("An Ed25519 offline trust key is required")
    manifest = json.loads(args.draft.read_text(encoding="utf-8"))
    if (
        manifest.get("domain") != DOMAIN
        or not manifest.get("signers")
        or not manifest.get("members")
    ):
        raise SystemExit(
            "Invalid trust draft; independently review all identities and keys first"
        )
    envelope = {
        "manifest": manifest,
        "signature": b64(key.sign(canonical_json(manifest).encode())),
    }
    write_new(args.output, (canonical_json(envelope) + "\n").encode())
    print(
        "Signed reviewed manifest. Upload this public envelope, never the private key."
    )


if __name__ == "__main__":
    main()
