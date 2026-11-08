"""Communities: groups of clans that each have their own oversight.

Afribit is the first community. Its oversight keys and laptop connection lines are in the
server settings (CLANS_CLAN_WALLET_OVERSIGHT_KEYS and ..._TOKEN_HASHES), and every clan without
a community belongs to it. Other communities are rows in `clan_communities`, each with its own
oversight keys and laptops. A clan joins one when its organizer gives the community's join
code. Each laptop sees and approves only its own community's clans.

Only the platform operator changes communities, with this command, run as the database owner:

    python -m clans.communities list
    python -m clans.communities create --name "Kibera Savers"       # prints the join code
    python -m clans.communities add-laptop kibera-savers --oversight-key "[fp/87'/1'/0']tpub..." \
        --token-hash <connection line>
    python -m clans.communities remove-laptop kibera-savers --token-hash <connection line>
    python -m clans.communities new-code kibera-savers

The web app can read communities but never change them, so a hacked web server can't swap a
community's oversight keys. Each clan wallet also keeps the keys it was built with.
"""

import argparse
import hashlib
import hmac
import re
import secrets
import sys
from dataclasses import dataclass

from sqlalchemy import JSON, Boolean, String, func, select
from sqlalchemy.orm import Mapped, mapped_column

from clans.db import Base
from clans.models import Clan, now_iso

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I/L
CODE_LENGTH = 8
MAX_OVERSIGHT_KEYS = 3


class Community(Base):
    __tablename__ = "clan_communities"
    id: Mapped[str] = mapped_column(
        String(40), primary_key=True
    )  # a short name, e.g. kibera-savers
    name: Mapped[str] = mapped_column(String(100))
    # Public keys of the community's oversight laptops. Any one of them can approve a payout.
    oversight_keys: Mapped[list] = mapped_column(JSON, default=list)
    # SHA-256 of each laptop's read token. A token can list payouts, never approve one.
    token_hashes: Mapped[list] = mapped_column(JSON, default=list)
    join_code_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[str] = mapped_column(String(40), default=now_iso)


@dataclass(frozen=True)
class Oversight:
    """Who oversees a clan: its community's name, oversight keys and laptops."""

    community_id: str | None  # None is the default community, from the settings
    name: str
    keys: tuple[str, ...]
    token_hashes: tuple[str, ...]


def default(settings) -> Oversight:
    return Oversight(
        None,
        settings.clan_default_community_name,
        tuple(settings.oversight_keys),
        tuple(settings.oversight_token_hashes),
    )


def _from_row(row: Community) -> Oversight:
    return Oversight(row.id, row.name, tuple(row.oversight_keys), tuple(row.token_hashes))


def for_clan(db, settings, clan_id: str) -> Oversight:
    clan = db.get(Clan, clan_id)
    if clan is None or clan.community_id is None:
        return default(settings)
    return _from_row(db.get(Community, clan.community_id))


def in_community(community_id: str | None):
    """The ids of every clan in one community, as a subquery."""
    rule = (
        Clan.community_id.is_(None) if community_id is None else Clan.community_id == community_id
    )
    return select(Clan.id).where(rule)


def normal_code(code: str) -> str:
    return "".join(code.split()).replace("-", "").upper()


def code_hash(code: str) -> str:
    return hashlib.sha256(("clans-community:" + normal_code(code)).encode()).hexdigest()


def by_code(db, code: str) -> Community | None:
    if len(normal_code(code)) != CODE_LENGTH:
        return None
    return db.scalar(
        select(Community).where(
            Community.join_code_hash == code_hash(code), Community.active.is_(True)
        )
    )


def reader(db, settings, token: str) -> Oversight | None:
    """The community a laptop's read token belongs to, or None if it isn't valid."""
    found = hashlib.sha256(token.encode()).hexdigest()
    # A closed community only stops taking new clans. Its laptops keep working.
    rows = db.scalars(select(Community)).all()
    matched = []
    for item in [default(settings), *(_from_row(row) for row in rows)]:
        # Compare with every hash, so the time taken doesn't show which one matched.
        checks = [hmac.compare_digest(found, value) for value in item.token_hashes]
        if any(checks):
            matched.append(item)
    return matched[0] if token and len(matched) == 1 else None


def any_readers(db, settings) -> bool:
    if settings.oversight_token_hashes:
        return True
    return any(row.token_hashes for row in db.scalars(select(Community)).all())


def view(oversight: Oversight) -> dict:
    """What members see about who oversees their clan."""
    return {"id": oversight.community_id, "name": oversight.name}


# ---------- the operator's command ----------


class CommunityError(Exception):
    pass


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40].strip("-")
    if len(slug) < 2:
        raise CommunityError("Give a name with at least two letters or digits")
    return slug


def new_code() -> str:
    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
    return code[:4] + "-" + code[4:]


def _check_key(value: str) -> str:
    from clans.clan_wallet import ClanWalletError, SignerKey

    try:
        return str(SignerKey.parse(value.strip()))
    except ClanWalletError as exc:
        raise CommunityError(f"That oversight key isn't valid: {exc}") from exc


def _check_hash(value: str) -> str:
    value = value.strip().lower()
    if len(value) != 64 or set(value) - set("0123456789abcdef"):
        raise CommunityError("A connection line is 64 characters, 0-9 and a-f")
    return value


def _taken(db, settings, *, keys=(), hashes=(), skip: str | None = None) -> None:
    """A key or a laptop belongs to one community only, so nobody can be unsure whose it is."""
    from clans.clan_wallet import SignerKey

    owners = [default(settings), *(_from_row(r) for r in db.scalars(select(Community)).all())]
    for owner in owners:
        if owner.community_id is not None and owner.community_id == skip:
            continue
        prints = {SignerKey.parse(k).fingerprint for k in owner.keys}
        for key in keys:
            if SignerKey.parse(key).fingerprint in prints:
                raise CommunityError(f"That oversight key already belongs to {owner.name}")
        for value in hashes:
            if value in owner.token_hashes:
                raise CommunityError(f"That connection line already belongs to {owner.name}")


def _wallets(db, community_id: str) -> int:
    from clans.wallet_models import ClanWalletRecord

    return db.scalar(
        select(func.count())
        .select_from(ClanWalletRecord)
        .where(ClanWalletRecord.clan_id.in_(in_community(community_id)))
    )


def _get(db, community_id: str) -> Community:
    row = db.get(Community, community_id)
    if row is None:
        raise CommunityError(f"There's no community '{community_id}'. Run list to see them")
    return row


def create(db, name: str) -> tuple[Community, str]:
    name = " ".join(name.split())
    if not 2 <= len(name) <= 100:
        raise CommunityError("A community name is 2 to 100 characters")
    slug = _slug(name)
    if db.get(Community, slug):
        raise CommunityError(f"A community called '{slug}' already exists")
    code = new_code()
    row = Community(
        id=slug, name=name, oversight_keys=[], token_hashes=[], join_code_hash=code_hash(code)
    )
    db.add(row)
    return row, code


def add_laptop(db, settings, community_id: str, key: str, token_hash: str) -> Community:
    row = _get(db, community_id)
    key, token_hash = _check_key(key), _check_hash(token_hash)
    if len(row.oversight_keys) >= MAX_OVERSIGHT_KEYS:
        raise CommunityError(f"A community has at most {MAX_OVERSIGHT_KEYS} oversight laptops")
    _taken(db, settings, keys=[key], hashes=[token_hash])
    row.oversight_keys = [*row.oversight_keys, key]
    row.token_hashes = [*row.token_hashes, token_hash]
    return row


def remove_laptop(
    db, community_id: str, *, key: str | None = None, token_hash: str | None = None, force=False
) -> Community:
    from clans.clan_wallet import SignerKey

    row = _get(db, community_id)
    if key:
        fingerprint = SignerKey.parse(_check_key(key)).fingerprint
        kept = [k for k in row.oversight_keys if SignerKey.parse(k).fingerprint != fingerprint]
        if len(kept) == len(row.oversight_keys):
            raise CommunityError("That oversight key isn't one of this community's")
        if _wallets(db, community_id) and not force:
            raise CommunityError(
                "Clan wallets already use this key, and keep using it. Remove it only if the "
                "laptop is gone for good, with --force, then move those clans to new wallets"
            )
        row.oversight_keys = kept
    if token_hash:
        value = _check_hash(token_hash)
        if value not in row.token_hashes:
            raise CommunityError("That connection line isn't one of this community's")
        row.token_hashes = [h for h in row.token_hashes if h != value]
    return row


def rotate_code(db, community_id: str) -> str:
    row = _get(db, community_id)
    code = new_code()
    row.join_code_hash = code_hash(code)
    return code


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    made = commands.add_parser("create")
    made.add_argument("--name", required=True)
    added = commands.add_parser("add-laptop")
    added.add_argument("community")
    added.add_argument("--oversight-key", required=True)
    added.add_argument("--token-hash", required=True)
    removed = commands.add_parser("remove-laptop")
    removed.add_argument("community")
    removed.add_argument("--oversight-key")
    removed.add_argument("--token-hash")
    removed.add_argument("--force", action="store_true")
    for name in ("new-code", "close", "reopen"):
        commands.add_parser(name).add_argument("community")
    args = parser.parse_args(argv)

    from clans.live_config import LiveSettings
    from clans.live_security import Security

    settings = LiveSettings()
    security = Security(settings)
    try:
        with security.db() as db:
            if args.command == "list":
                first = default(settings)
                print(
                    f"{first.name} (default): {len(first.keys)} oversight key(s), "
                    f"{len(first.token_hashes)} laptop(s), set in the server settings"
                )
                for row in db.scalars(select(Community).order_by(Community.created_at)).all():
                    clans = db.scalar(
                        select(func.count()).select_from(Clan).where(Clan.community_id == row.id)
                    )
                    state = "" if row.active else ", closed to new clans"
                    print(
                        f"{row.name} ({row.id}): {len(row.oversight_keys)} oversight key(s), "
                        f"{len(row.token_hashes)} laptop(s), {clans} clan(s){state}"
                    )
            elif args.command == "create":
                row, code = create(db, args.name)
                print(f"Created {row.name} ({row.id}). Join code: {code}")
                print("Organizers type the join code when they create a clan. It's shown once.")
                print(f"Next: add-laptop {row.id} with each oversight laptop's two lines.")
            elif args.command == "add-laptop":
                row = add_laptop(db, settings, args.community, args.oversight_key, args.token_hash)
                print(f"Added. {row.name} has {len(row.oversight_keys)} oversight laptop(s).")
                print("Clan wallets made from now on include it. Existing ones keep their keys.")
            elif args.command == "remove-laptop":
                if not (args.oversight_key or args.token_hash):
                    raise CommunityError("Give --oversight-key, --token-hash, or both")
                row = remove_laptop(
                    db,
                    args.community,
                    key=args.oversight_key,
                    token_hash=args.token_hash,
                    force=args.force,
                )
                print(f"Removed. {row.name} has {len(row.oversight_keys)} oversight key(s).")
            elif args.command == "new-code":
                print(
                    f"New join code: {rotate_code(db, args.community)}. The old one stops working."
                )
            else:
                row = _get(db, args.community)
                row.active = args.command == "reopen"
                print(
                    f"{row.name} is {'open' if row.active else 'closed'} to new clans. "
                    "Its clans and laptops keep working."
                )
    except CommunityError as exc:
        print(f"{exc}.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
