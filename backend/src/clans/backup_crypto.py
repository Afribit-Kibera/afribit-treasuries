"""Versioned encrypted backup envelope using the existing cryptography dependency.

RSA-OAEP wraps a fresh AES-256-GCM key. Header and ciphertext are authenticated.
Decryption must finish successfully before any plaintext is accepted for restore.
"""

import json
import secrets

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

MAGIC = b"AFRIBIT-BACKUP-1\n"


def oaep():
    return padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=MAGIC)


def encrypt(source, destination, recipient):
    if not isinstance(recipient, rsa.RSAPublicKey) or recipient.key_size < 3072:
        raise ValueError("Backup recipient must be an RSA public key of at least 3072 bits")
    key, nonce = secrets.token_bytes(32), secrets.token_bytes(12)
    header = (
        MAGIC
        + json.dumps(
            {"wrapped_key": recipient.encrypt(key, oaep()).hex(), "nonce": nonce.hex()},
            sort_keys=True,
        ).encode()
        + b"\n"
    )
    cipher = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    cipher.authenticate_additional_data(header)
    destination.write(header)
    while chunk := source.read(1024 * 1024):
        destination.write(cipher.update(chunk))
    destination.write(cipher.finalize())
    destination.write(cipher.tag)


def decrypt(source, destination, private_key):
    """Destination is untrusted partial plaintext UNTIL this function returns."""
    if source.readline(len(MAGIC) + 1) != MAGIC:
        raise ValueError("Unknown backup format")
    raw = source.readline(8193)
    if len(raw) > 8192 or not raw.endswith(b"\n"):
        raise ValueError("Invalid backup header")
    header = json.loads(raw)
    key = private_key.decrypt(bytes.fromhex(header["wrapped_key"]), oaep())
    cipher = Cipher(algorithms.AES(key), modes.GCM(bytes.fromhex(header["nonce"]))).decryptor()
    cipher.authenticate_additional_data(MAGIC + raw)
    tail = b""
    while chunk := source.read(1024 * 1024):
        combined = tail + chunk
        if len(combined) > 16:
            destination.write(cipher.update(combined[:-16]))
        tail = combined[-16:]
    if len(tail) != 16:
        raise ValueError("Truncated backup")
    destination.write(cipher.finalize_with_tag(tail))
