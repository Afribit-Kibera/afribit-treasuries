import re

RESERVED = {"admin", "administrator", "support", "afribit", "clans", "security", "system", "root"}


def normalize(value: str) -> str:
    value = value.strip().lower()
    if not re.fullmatch(r"[a-z][a-z0-9_]{2,23}", value) or value in RESERVED:
        raise ValueError("Choose 3–24 letters, numbers or underscores. Start with a letter.")
    return value
