"""Local envelope round trips/tamper checks; no database, SSH or real secrets."""

import io
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from clans.backup import validate_target
from clans.backup_crypto import decrypt, encrypt


@pytest.fixture(scope="module")
def recipient():
    return rsa.generate_private_key(public_exponent=65537, key_size=3072)


@pytest.mark.parametrize("size", [0, 1, 15, 16, 17, 1024 * 1024 + 37])
def test_encrypted_backup_round_trip(recipient, size):
    plaintext = (b"private account and treasury data\x00" * (size // 33 + 1))[:size]
    encrypted = io.BytesIO()
    encrypt(io.BytesIO(plaintext), encrypted, recipient.public_key())
    result = io.BytesIO()
    decrypt(io.BytesIO(encrypted.getvalue()), result, recipient)
    assert result.getvalue() == plaintext
    assert encrypted.getvalue() != plaintext


@pytest.mark.parametrize("part", ["header", "ciphertext", "tag", "truncated"])
def test_modified_backup_never_authenticates(recipient, part):
    encrypted = io.BytesIO()
    encrypt(io.BytesIO(b"sensitive backup" * 100), encrypted, recipient.public_key())
    data = bytearray(encrypted.getvalue())
    if part == "truncated":
        data = data[:-8]
    else:
        index = {"header": 0, "ciphertext": len(data) - 20, "tag": len(data) - 1}[part]
        data[index] ^= 1
    with pytest.raises((ValueError, InvalidTag)):
        decrypt(io.BytesIO(data), io.BytesIO(), recipient)


def test_wrong_recipient_cannot_decrypt(recipient):
    encrypted = io.BytesIO()
    encrypt(io.BytesIO(b"private"), encrypted, recipient.public_key())
    other = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    with pytest.raises(ValueError):
        decrypt(io.BytesIO(encrypted.getvalue()), io.BytesIO(), other)


def test_small_recipient_key_is_rejected():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(ValueError):
        encrypt(io.BytesIO(b"private"), io.BytesIO(), key.public_key())


@pytest.mark.parametrize(
    "value",
    [
        "-oProxyCommand=bad",
        "user@host:/x;bad",
        "user@host:relative",
        "user@host:/x/../y",
        "user@host:/x\ncommand",
        "user@host:/x space",
    ],
)
def test_backup_remote_target_rejects_command_or_path_injection(value):
    with pytest.raises(ValueError):
        validate_target(value)


def test_backup_remote_target_accepts_fixed_destination():
    assert validate_target("backups@backup.example:/clans/archives/") == (
        "backups@backup.example:/clans/archives"
    )


@pytest.mark.parametrize("tamper", [False, True])
def test_offline_decryption_cli_publishes_only_authenticated_output(recipient, tmp_path, tamper):
    encrypted = io.BytesIO()
    encrypt(io.BytesIO(b"private database archive"), encrypted, recipient.public_key())
    data = bytearray(encrypted.getvalue())
    if tamper:
        data[-1] ^= 1
    archive, keyfile, output = [tmp_path / n for n in ["backup.enc", "offline.key", "out.dump"]]
    archive.write_bytes(data)
    keyfile.write_bytes(
        recipient.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    script = Path(__file__).resolve().parents[2] / "scripts/decrypt_backup.py"
    command = [
        sys.executable,
        str(script),
        "--archive",
        str(archive),
        "--private-key",
        str(keyfile),
        "--output",
        str(output),
    ]
    result = subprocess.run(command, capture_output=True, timeout=20, check=False)
    assert (result.returncode == 0) is not tamper
    assert output.exists() is not tamper
    assert not output.with_name(output.name + ".unauthenticated-partial").exists()
    if not tamper:
        assert output.read_bytes() == b"private database archive"
        assert subprocess.run(command, capture_output=True, timeout=20, check=False).returncode != 0
