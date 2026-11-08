"""The oversight desktop app's core: one JSON request per line on stdin, one answer per line out.

The desktop app (oversight-desktop/) starts it with its bundled Python:

    python.exe -I -m clans.oversight_service --home <data folder> --url <Clans address>

A request is {"id": 1, "command": "overview", "args": {...}}. The answer is
{"id": 1, "ok": true, "result": ...} or {"id": 1, "ok": false, "error": "...", "code": "..."}.

Every check is the one in clans.oversight. The screens never see a PSBT and never choose an
address: they send payout ids, the characters a person typed, and the passphrase. This module
adds two rules, because a screen can be slow or out of date:

* approve fetches the payout again and signs only if it's the payment the person read: the same
  txid and the same total.
* approve refuses while there are unread alarms, as the console app does.
"""

import argparse
import json
import sys
import traceback
from pathlib import Path
from typing import Any

from clans import oversight as ov
from clans import oversight_guide as guide

PROTOCOL = 1
MAX_LINE = 64 * 1024
RECENT_ALARMS = 20
RECENT_APPROVALS = 20


class Refused(Exception):
    """A request the app shouldn't have sent. The message says why."""


class Check(ov.OversightError):
    """A failed check the screens handle in their own way, told apart by `reason`."""

    def __init__(self, message: str, reason: str):
        super().__init__(message)
        self.reason = reason


def _unlocked(home: Path, passphrase: str) -> None:
    try:
        ov.unlock(home, passphrase)
    except ov.WrongPassphrase as exc:
        raise Check(str(exc), "wrong_passphrase") from exc


def _is_bech32(address: str) -> bool:
    return address.lower().startswith(("bc1", "tb1", "bcrt1"))


def _text(value: Any, name: str, limit: int = 256) -> str:
    if not isinstance(value, str) or len(value) > limit:
        raise Refused(f"{name} must be text")
    return value


def _id(value: Any, name: str) -> str:
    value = _text(value, name, 64)
    if not ov.SAFE_ID.match(value):
        raise Refused(f"{name} isn't a valid id")
    return value


def _whole(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise Refused(f"{name} must be a whole number")
    return value


def _digits(typed: str) -> str:
    return typed.replace(",", "").replace(" ", "").strip()


class Service:
    def __init__(self, home: Path, url: str | None = None):
        self.home = home
        self.url = url
        # Payouts as last fetched, so an address check uses the core's own copy.
        self.payouts: dict[str, dict] = {}

    # ---------- this laptop ----------

    def status(self) -> dict:
        has_key = (self.home / ov.KEY_FILE).exists()
        connected = (self.home / ov.SERVER_FILE).exists()
        server = None
        if connected:
            server = json.loads((self.home / ov.SERVER_FILE).read_text(encoding="utf-8"))["url"]
        mainnet = None
        if has_key:
            mainnet = ov._key_file(self.home).get("mainnet_public_key")
        return {
            "protocol": PROTOCOL,
            "has_key": has_key,
            "connected": connected,
            "server": server,
            "default_server": self.url,
            "home": str(self.home),
            "has_mainnet_key": bool(mainnet),
            "registered_wallets": len(ov.load_register(self.home)["wallets"]),
        }

    def create_key(self, passphrase: str) -> dict:
        words, public = ov.create_key(self.home, passphrase)
        return {"words": words.split(), "public_key": public}

    def restore_key(self, words: str, passphrase: str) -> dict:
        try:
            ov._account(words)
        except ov.OversightError as exc:
            raise Check(str(exc), "bad_words") from exc
        _, public = ov.create_key(self.home, passphrase, words)
        return {"public_key": public}

    def check_passphrase(self, passphrase: str) -> dict:
        """Proves the key opens. Also adds the mainnet public key to an older key file."""
        _unlocked(self.home, passphrase)
        return {"ok": True}

    def check_words(self, passphrase: str, answers: dict) -> dict:
        """Checks the person's paper copy: the words they typed at the numbers the screen chose."""
        if not 1 <= len(answers) <= 12:
            raise Refused("Give between 1 and 12 words")
        try:
            typed = {int(number): _text(word, "word", 20) for number, word in answers.items()}
        except ValueError as exc:
            raise Refused("Each word needs its number, 1 to 12") from exc
        if not all(1 <= number <= 12 for number in typed):
            raise Refused("Each word needs its number, 1 to 12")
        _unlocked(self.home, passphrase)
        words = ov.open_words(self.home, passphrase).split()
        wrong = sorted(n for n, word in typed.items() if word.strip().lower() != words[n - 1])
        return {"matches": not wrong, "wrong": wrong}

    def connect(self, url: str | None = None) -> dict:
        if (self.home / ov.SERVER_FILE).exists():
            raise ov.OversightError(
                "This laptop is already connected. Connecting again would make a new connection "
                "line, and the administrator would have to add it again"
            )
        address = url or self.url
        if not address:
            raise ov.OversightError("Type the Clans address, for example https://clans.example.org")
        digest = ov.connect(self.home, address)
        return {"connection_line": digest, "admin_text": guide.admin_text(self.home)}

    def admin_lines(self) -> dict:
        return {"text": guide.admin_text(self.home)}

    def records(self) -> dict:
        register = ov.load_register(self.home)
        names = {cid: saved.get("clan_name") or "" for cid, saved in register["wallets"].items()}
        return {
            "addresses": [
                {"name": saved["name"], "address": address, "confirmed_at": saved["confirmed_at"]}
                for address, saved in register["addresses"].items()
            ],
            "approvals": [
                {
                    "signed_at": item["signed_at"],
                    "clan_id": item["clan_id"],
                    "clan_name": names.get(item["clan_id"], ""),
                    "kind": item.get("kind", "grant"),
                    "total_sats": item["total_sats"],
                    "fee_sats": item["fee_sats"],
                    "txid": item["txid"],
                }
                for item in reversed(register["payouts"][-RECENT_APPROVALS:])
            ],
            "settings": register["settings"],
            "register_file": str(self.home / ov.REGISTER_FILE),
        }

    def clans(self) -> list[dict]:
        found = []
        for clan_id, saved in ov.load_register(self.home)["wallets"].items():
            policy = ov._policy(saved["policy"])
            found.append(
                {
                    "clan_id": clan_id,
                    "clan_name": saved.get("clan_name") or "",
                    "generation": saved["generation"],
                    "wallet_code": saved["wallet_code"],
                    "network": policy.network,
                    "threshold": policy.threshold,
                    "signers": len(policy.signers),
                }
            )
        return sorted(found, key=lambda item: (item["clan_name"] or item["clan_id"]).lower())

    def funding_address(self, clan_id: str) -> dict:
        address = ov.clan_address(self.home, clan_id)
        start, end = ov.check_characters(address)
        return {
            "address": address,
            "fixed_start": ov.fixed_start(address),
            "check_start": start,
            "check_end": end,
        }

    # ---------- the Clans server ----------

    def overview(self) -> dict:
        try:
            with ov.server(self.home) as client:
                waiting = ov.pending(client)
                unread = ov.unread_alarms(self.home, client)
                new_wallets = ov.unregistered(self.home, client)
                community = guide.community_name(client)
        except ov.OversightError as exc:
            text = str(exc)
            ready = "(401)" not in text and "(503)" not in text
            return {
                "answered": False,
                "reason": "unreachable" if ready else "not_added",
                "message": text,
                "networks": self._networks(),
            }
        self.payouts = {str(item.get("id")): item for item in waiting}
        return {
            "answered": True,
            "community": community,
            "networks": self._networks(),
            "alarms": [_alarm(item) for item in unread],
            "wallets_to_register": [_wallet(item) for item in new_wallets],
            "payouts": [_summary(item) for item in waiting],
        }

    def _networks(self) -> list[str]:
        wallets = ov.load_register(self.home)["wallets"].values()
        return sorted({saved["policy"]["network"] for saved in wallets})

    def alarms(self, recent: bool = False) -> list[dict]:
        """Unread alarms, or with `recent` the latest ones whether read or not."""
        with ov.server(self.home) as client:
            if recent:
                found = ov.alarms(client)[:RECENT_ALARMS]
            else:
                found = ov.unread_alarms(self.home, client)
        return [_alarm(item) for item in found]

    def mark_alarms_read(self, newest: str) -> dict:
        """Marks read the unread alarms up to the newest one the person was shown."""
        with ov.server(self.home) as client:
            unread = ov.unread_alarms(self.home, client)
            seen = [item for item in unread if item["created_at"] <= newest]
            ov.mark_alarms_read(self.home, seen)
            return {"unread": len(ov.unread_alarms(self.home, client))}

    def register_wallet(self, clan_id: str, generation: int, code: str) -> dict:
        with ov.server(self.home) as client:
            found = [
                item
                for item in ov.unregistered(self.home, client, clan_id)
                if item["generation"] == generation
            ]
        if not found:
            raise ov.OversightError(
                "This wallet is already registered, or Clans no longer lists it"
            )
        expected = ov._policy(found[0].get("policy") or found[0]).wallet_code()
        if "".join(code.split()).replace("-", "").lower() != expected:
            raise Check(
                "The wallet code doesn't match the signatory's phone. Don't approve anything for "
                "this clan, and tell the clan and Afribit",
                "code_mismatch",
            )
        policy = ov.add_wallet(self.home, clan_id, found[0], code)
        return {
            "clan_name": found[0].get("clan_name") or "",
            "threshold": policy.threshold,
            "signers": len(policy.signers),
        }

    def _fetch(self, client, payout_id: str) -> dict:
        waiting = ov.pending(client)
        self.payouts = {str(item.get("id")): item for item in waiting}
        payout = self.payouts.get(payout_id)
        if payout is None:
            raise Check(
                "This payout isn't waiting for you any more. It may have been approved on "
                "another laptop or replaced",
                "payout_gone",
            )
        return payout

    def open_payout(self, payout_id: str) -> dict:
        """The next step for one payout: a wallet to register, an address to check, or review."""
        with ov.server(self.home) as client:
            payout = self._fetch(client, payout_id)
            clan_id = str(payout.get("clan_id", ""))
            saved = ov.load_register(self.home)["wallets"].get(clan_id)
            known = (
                {item["generation"] for item in [saved, *saved.get("earlier", [])]}
                if saved
                else set()
            )
            destination = payout.get("destination") or {}
            needed = {payout.get("generation"), destination.get("generation")} - {None}
            if not needed <= known:
                missing = [
                    _wallet(item)
                    for item in ov.unregistered(self.home, client, clan_id)
                    if item["generation"] in needed
                ]
                if not missing:
                    return {
                        "step": "stopped",
                        "payout": _summary(payout),
                        "message": (
                            "Clans doesn't list the clan wallet this payout spends from, so this "
                            "laptop can't check it"
                        ),
                    }
                return {"step": "wallet", "payout": _summary(payout), "wallets": missing}
            unread = len(ov.unread_alarms(self.home, client))
        if payout.get("kind", "grant") == "grant":
            confirmed = ov.load_register(self.home)["addresses"]
            for line, item in enumerate(payout.get("recipients") or []):
                address = str(item.get("address", ""))
                if address and address not in confirmed:
                    # The address itself isn't sent: the beneficiary reads it from their wallet.
                    return {
                        "step": "address",
                        "payout": _summary(payout),
                        "line": line,
                        "name": str(item.get("name") or ""),
                        "fixed_start": ov.fixed_start(address),
                        "characters": 2 * ov.CHECK_CHARACTERS,
                    }
        try:
            checked = ov.review(self.home, payout)
        except ov.OversightError as exc:
            return {"step": "stopped", "payout": _summary(payout), "message": str(exc)}
        saved = ov.load_register(self.home)["wallets"][checked.clan_id]
        network = ov._generation(saved, checked.generation)["policy"]["network"]
        return {
            "step": "review",
            "payout": _summary(payout),
            "review": {**_review(checked, payout), "network": network},
            "unread_alarms": unread,
        }

    def confirm_address(self, payout_id: str, line: int, characters: str) -> dict:
        payout = self.payouts.get(payout_id)
        recipients = (payout or {}).get("recipients") or []
        if payout is None or line >= len(recipients):
            raise Refused("Open the payout first")
        typed = "".join(characters.split())
        if len(typed) != 2 * ov.CHECK_CHARACTERS:
            raise ov.OversightError(
                f"That's {len(typed)} characters. Type all {2 * ov.CHECK_CHARACTERS}: the first "
                f"{ov.CHECK_CHARACTERS}, then the last {ov.CHECK_CHARACTERS}"
            )
        saved = ov.load_register(self.home)["wallets"].get(str(payout.get("clan_id", "")))
        if not saved:
            raise Refused("Register the clan's wallet first")
        recipient = recipients[line]
        address = str(recipient.get("address", "")).strip()
        expected = ov.check_characters(address)
        heard = (typed[: ov.CHECK_CHARACTERS], typed[ov.CHECK_CHARACTERS :])
        if _is_bech32(address):
            # Bech32 addresses don't depend on capitals; people read them either way.
            expected = tuple(part.lower() for part in expected)
            heard = tuple(part.lower() for part in heard)
        if heard != expected:
            raise Check(
                "The characters the beneficiary read don't match. Don't use this address. Ask "
                "them to check their wallet, and tell Afribit if it still differs",
                "address_mismatch",
            )
        ov.confirm_address(
            self.home,
            address,
            str(recipient.get("name") or ""),
            *ov.check_characters(address),
            saved["policy"]["network"],
        )
        return {"confirmed": True}

    def approve(
        self, payout_id: str, passphrase: str, shown: dict, typed_total: str | None = None
    ) -> dict:
        """Check again, sign and upload. Signs only the payment the person read."""
        txid = _text(shown.get("txid"), "shown.txid", 64)
        total = _whole(shown.get("total_sats"), "shown.total_sats")
        # The passphrase first, so a typing mistake doesn't use up the server's rate limit.
        _unlocked(self.home, passphrase)
        with ov.server(self.home) as client:
            if ov.unread_alarms(self.home, client):
                raise Check("There are new alarms. Read them before approving", "alarms_unread")
            payout = self._fetch(client, payout_id)
            checked = ov.review(self.home, payout)
            if checked.txid != txid or checked.total_sats != total:
                raise Check(
                    "This payout changed since you opened it. Nothing was signed. Open it again "
                    "and check it from the start",
                    "payout_changed",
                )
            if checked.large and _digits(typed_total or "") != str(checked.total_sats):
                raise Check("That isn't the total. Nothing was signed", "wrong_total")
            signed, complete = ov.sign(self.home, payout, passphrase)
            result = ov.upload(client, ov.signed_file(payout, checked, signed))
        got = result.get("signatures") or {}
        return {
            "approved": True,
            "complete": complete,
            "signatures": {"count": got.get("count"), "required": got.get("required")},
        }


def _alarm(item: dict) -> dict:
    return {
        "created_at": item["created_at"],
        "kind": item["kind"],
        "message": item.get("message") or "",
        "clan_id": item.get("clan_id"),
        "clan_name": item.get("clan_name") or "",
        "generation": item.get("generation"),
        "detail": item.get("detail") or {},
    }


def _wallet(item: dict) -> dict:
    return {
        "clan_id": item["clan_id"],
        "clan_name": item.get("clan_name") or "",
        "generation": item["generation"],
    }


def _summary(payout: dict) -> dict:
    """What the list shows, as Clans describes it. The checked figures come from review."""
    return {
        "id": str(payout.get("id")),
        "clan_id": str(payout.get("clan_id", "")),
        "clan_name": payout.get("clan_name") or "",
        "kind": payout.get("kind", "grant"),
        "created_at": payout.get("created_at"),
        "beneficiaries": [str(item.get("name") or "") for item in payout.get("recipients") or []],
        "approved_sats": sum(
            int(item.get("approved_sats") or 0) for item in payout.get("recipients") or []
        ),
    }


def _review(checked: ov.Review, payout: dict) -> dict:
    lines = []
    for name, address, approved, received in checked.lines:
        start, end = ov.check_characters(address)
        lines.append(
            {
                "name": name,
                "address": address,
                "fixed_start": ov.fixed_start(address),
                "check_start": start,
                "check_end": end,
                "approved_sats": approved,
                "received_sats": received,
            }
        )
    return {
        "clan_id": checked.clan_id,
        "clan_name": payout.get("clan_name") or "",
        "kind": checked.kind,
        "generation": checked.generation,
        "txid": checked.txid,
        "lines": lines,
        "fee_sats": checked.fee_sats,
        "fee_paid_by": checked.fee_paid_by,
        "total_sats": checked.total_sats,
        "large": checked.large,
        "replaces": list(checked.replaces),
        "already_signed": checked.already_signed,
        "destination": checked.destination,
    }


# Each command and the arguments it takes: name -> (checker, required).
COMMANDS: dict[str, dict[str, tuple[Any, bool]]] = {
    "status": {},
    "create_key": {"passphrase": (lambda v: _text(v, "passphrase", 1024), True)},
    "restore_key": {
        "words": (lambda v: _text(v, "words", 400), True),
        "passphrase": (lambda v: _text(v, "passphrase", 1024), True),
    },
    "check_passphrase": {"passphrase": (lambda v: _text(v, "passphrase", 1024), True)},
    "check_words": {
        "passphrase": (lambda v: _text(v, "passphrase", 1024), True),
        "answers": (lambda v: v if isinstance(v, dict) else _text(None, "answers"), True),
    },
    "connect": {"url": (lambda v: _text(v, "url", 200), False)},
    "admin_lines": {},
    "records": {},
    "clans": {},
    "funding_address": {"clan_id": (lambda v: _id(v, "clan_id"), True)},
    "overview": {},
    "alarms": {"recent": (lambda v: bool(v), False)},
    "mark_alarms_read": {"newest": (lambda v: _text(v, "newest", 64), True)},
    "register_wallet": {
        "clan_id": (lambda v: _id(v, "clan_id"), True),
        "generation": (lambda v: _whole(v, "generation"), True),
        "code": (lambda v: _text(v, "code", 40), True),
    },
    "open_payout": {"payout_id": (lambda v: _id(v, "payout_id"), True)},
    "confirm_address": {
        "payout_id": (lambda v: _id(v, "payout_id"), True),
        "line": (lambda v: _whole(v, "line"), True),
        "characters": (lambda v: _text(v, "characters", 64), True),
    },
    "approve": {
        "payout_id": (lambda v: _id(v, "payout_id"), True),
        "passphrase": (lambda v: _text(v, "passphrase", 1024), True),
        "shown": (lambda v: v if isinstance(v, dict) else _text(None, "shown"), True),
        "typed_total": (lambda v: None if v is None else _text(v, "typed_total", 40), False),
    },
}


def handle(service: Service, line: str) -> dict:
    """Answer one request line. Never raises."""
    request_id = None
    try:
        if len(line) > MAX_LINE:
            raise Refused("The request is too long")
        try:
            request = json.loads(line)
        except ValueError as exc:
            raise Refused("The request isn't valid JSON") from exc
        if not isinstance(request, dict):
            raise Refused("The request isn't valid")
        request_id = request.get("id")
        command = request.get("command")
        spec = COMMANDS.get(command) if isinstance(command, str) else None
        if spec is None:
            raise Refused("Unknown command")
        given = request.get("args") or {}
        if not isinstance(given, dict) or set(given) - set(spec):
            raise Refused(f"Unexpected arguments for {command}")
        args = {}
        for name, (check, required) in spec.items():
            if name in given:
                args[name] = check(given[name])
            elif required:
                raise Refused(f"{command} needs {name}")
        result = getattr(service, command)(**args)
        return {"id": request_id, "ok": True, "result": result}
    except ov.OversightError as exc:
        answer = {"id": request_id, "ok": False, "error": str(exc), "code": "check"}
        if isinstance(exc, Check):
            answer["reason"] = exc.reason
        return answer
    except Refused as exc:
        return {"id": request_id, "ok": False, "error": str(exc), "code": "refused"}
    except Exception as exc:  # the app shows this and keeps running
        traceback.print_exc(file=sys.stderr)
        return {
            "id": request_id,
            "ok": False,
            "error": (
                f"Something went wrong ({type(exc).__name__}). Nothing was signed unless the "
                "app said it was approved. Tell the team"
            ),
            "code": "internal",
        }


def serve(service: Service, reader, writer, refusal: str | None = None) -> None:
    """Answer each line until the app closes stdin. With `refusal`, every answer is that error."""
    for line in reader:
        if not line.strip():
            continue
        if refusal:
            try:
                request_id = json.loads(line).get("id")
            except (ValueError, AttributeError):
                request_id = None
            answer = {"id": request_id, "ok": False, "error": refusal, "code": "check"}
        else:
            answer = handle(service, line.rstrip("\r\n"))
        writer.write(json.dumps(answer) + "\n")
        writer.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m clans.oversight_service")
    parser.add_argument("--home", type=Path, default=None)
    parser.add_argument("--url", default=None)
    args = parser.parse_args(argv)
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    # Answers go only to the real stdout. Anything else printed goes to stderr.
    answers, sys.stdout = sys.stdout, sys.stderr
    home = args.home or ov.default_home()
    core = Service(home, args.url)
    try:
        with ov.only_one_app(home):
            serve(core, sys.stdin, answers)
    except ov.OversightError as exc:
        # Another window holds this laptop's files. Say so to every request until closed.
        serve(core, sys.stdin, answers, refusal=str(exc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
