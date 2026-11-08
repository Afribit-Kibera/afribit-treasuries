"""128-bit, checksummed account recovery words. No Bitcoin keys are derived."""

import hashlib
import re
import secrets
from functools import cache
from importlib.resources import files


@cache
def wordlist() -> tuple[str, ...]:
    return tuple(files("clans").joinpath("data/bip39-english.txt").read_text().split())


def encode(entropy: bytes) -> str:
    if len(entropy) != 16:
        raise ValueError("Recovery needs 128 random bits")
    value = (int.from_bytes(entropy, "big") << 4) | (hashlib.sha256(entropy).digest()[0] >> 4)
    words = wordlist()
    return " ".join(words[(value >> (11 * index)) & 2047] for index in range(11, -1, -1))


def generate() -> str:
    return encode(secrets.token_bytes(16))


def hash_input(value: str) -> str:
    canonical = " ".join(value.lower().split())
    words = canonical.split()
    if len(words) == 12:
        indices = {word: index for index, word in enumerate(wordlist())}
        try:
            number = 0
            for word in words:
                number = (number << 11) | indices[word]
        except KeyError as exc:
            raise ValueError("Check your recovery words") from exc
        entropy = (number >> 4).to_bytes(16, "big")
        if encode(entropy) != canonical:
            raise ValueError("Check the order of your recovery words")
        return "recovery-words-v1:" + canonical
    # Existing kits remain usable until consumed or replaced.
    legacy = re.sub(r"[\s-]", "", canonical)
    if re.fullmatch(r"[0-9a-f]{24}", legacy):
        return "recovery:" + legacy
    raise ValueError("Enter your 12 recovery words or your older recovery code")
