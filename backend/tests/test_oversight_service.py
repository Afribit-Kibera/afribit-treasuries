"""The desktop app's core, driven with the JSON lines the app sends."""

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import bdkpython as bdk
import test_clan_wallet_payments as payments
from clan_wallet_helpers import DESTINATION
from fastapi.testclient import TestClient
from test_clan_wallet_payments import afribit_only_alarm, ready_payout, sign, tick
from test_live_app import ORIGIN

from clans import oversight as ov
from clans import oversight_guide as guide
from clans import oversight_service as service

clan, keys = payments.clan, payments.keys

PASSPHRASE = "correct horse battery staple"
WORDS = str(bdk.Mnemonic.from_entropy(bytes([1]) * 16))  # the clan fixture's oversight key


class App:
    """Sends requests the way the desktop shell does, one JSON line each."""

    def __init__(self, home, url=ORIGIN):
        self.core = service.Service(home, url)
        self.sent = 0

    def answer(self, command, **args):
        self.sent += 1
        line = json.dumps({"id": self.sent, "command": command, "args": args})
        reply = service.handle(self.core, line)
        assert reply["id"] == self.sent
        return reply

    def __call__(self, command, **args):
        reply = self.answer(command, **args)
        assert reply["ok"], reply
        return reply["result"]

    def refused(self, command, **args):
        reply = self.answer(command, **args)
        assert not reply["ok"], reply
        return reply["error"]


def laptop_on_clans(clan, home, monkeypatch):
    def laptop(_home):
        token = json.loads((home / ov.SERVER_FILE).read_text(encoding="utf-8"))["token"]
        headers = {"Authorization": "Bearer " + token}
        return TestClient(clan["app"], base_url=ORIGIN, headers=headers)

    monkeypatch.setattr(ov, "server", laptop)


def signed_by_the_clan(clan):
    _, second, third = clan["signers"]
    _, payout = ready_payout(clan)
    sign(clan, third, sign(clan, second, payout).json())
    return payout


def set_up(clan, home, monkeypatch):
    app = App(home)
    app("restore_key", words=WORDS, passphrase=PASSPHRASE)
    line = app("connect")["connection_line"]
    clan["app"].state.security.settings.clan_wallet_oversight_token_hashes = line
    laptop_on_clans(clan, home, monkeypatch)
    return app


def test_a_new_laptop_makes_its_key_and_connects(tmp_path):
    app = App(tmp_path / "laptop")
    assert app("status")["has_key"] is False
    assert "12 characters" in app.refused("create_key", passphrase="short")
    made = app("create_key", passphrase=PASSPHRASE)
    assert len(made["words"]) == 12
    assert "already has" in app.refused("create_key", passphrase=PASSPHRASE)
    connected = app("connect")
    assert connected["connection_line"] in connected["admin_text"]
    assert " ".join(made["words"]) not in connected["admin_text"]
    # A second connect would make a new line the administrator doesn't know.
    assert "already connected" in app.refused("connect")
    status = app("status")
    assert status["has_key"] and status["connected"] and status["server"] == ORIGIN
    assert app("check_passphrase", passphrase=PASSPHRASE) == {"ok": True}
    assert "Wrong passphrase" in app.refused("check_passphrase", passphrase="not the passphrase")


def test_a_payout_goes_from_wallet_code_to_address_to_approval(clan, tmp_path, monkeypatch):
    home = tmp_path / "laptop"
    app = set_up(clan, home, monkeypatch)
    payout = signed_by_the_clan(clan)

    seen = app("overview")
    assert seen["answered"] and seen["alarms"] == []
    assert [item["clan_id"] for item in seen["wallets_to_register"]] == [clan["cid"]]
    (listed,) = seen["payouts"]
    assert listed["id"] == payout["id"] and "psbt" not in listed

    step = app("open_payout", payout_id=payout["id"])
    assert step["step"] == "wallet"
    code = clan["policy"].wallet_code()
    wrong = app.refused("register_wallet", clan_id=clan["cid"], generation=1, code="wrongcod")
    assert "doesn't match" in wrong
    app("register_wallet", clan_id=clan["cid"], generation=1, code=code[:4] + "-" + code[4:])

    step = app("open_payout", payout_id=payout["id"])
    assert step["step"] == "address" and step["fixed_start"] == ov.fixed_start(DESTINATION)
    # The screen must not be able to show the address before the beneficiary reads it.
    assert DESTINATION not in json.dumps(step)
    start, end = ov.check_characters(DESTINATION)
    assert "don't match" in app.refused(
        "confirm_address", payout_id=payout["id"], line=0, characters="aaaaaa bbbbbb"
    )
    app("confirm_address", payout_id=payout["id"], line=0, characters=f"{start} {end}")

    step = app("open_payout", payout_id=payout["id"])
    assert step["step"] == "review"
    shown = step["review"]
    assert shown["txid"] == payout["txid"] and shown["lines"][0]["address"] == DESTINATION
    assert shown["lines"][0]["check_start"] == start

    # Approving something other than what was read signs nothing.
    changed = {"txid": "0" * 64, "total_sats": shown["total_sats"]}
    assert "changed since you opened it" in app.refused(
        "approve", payout_id=payout["id"], passphrase=PASSPHRASE, shown=changed
    )
    assert ov.load_register(home)["payouts"] == []
    shown_now = {"txid": shown["txid"], "total_sats": shown["total_sats"]}
    assert "Wrong passphrase" in app.refused(
        "approve", payout_id=payout["id"], passphrase="not the passphrase", shown=shown_now
    )
    done = app("approve", payout_id=payout["id"], passphrase=PASSPHRASE, shown=shown_now)
    assert done["approved"] is True
    assert app("overview")["payouts"] == []
    tick(clan)
    assert clan["chain"].broadcasts == [payout["txid"]]
    assert app("records")["approvals"][0]["txid"] == payout["txid"]
    assert "isn't waiting" in app.refused(
        "approve", payout_id=payout["id"], passphrase=PASSPHRASE, shown=shown_now
    )


def ready_to_approve(clan, home, monkeypatch):
    app = set_up(clan, home, monkeypatch)
    view = clan["signers"][0].get(f"/api/clans/{clan['cid']}/wallet").json()
    ov.add_wallet(home, clan["cid"], view, clan["policy"].wallet_code())
    start, end = ov.check_characters(DESTINATION)
    ov.confirm_address(home, DESTINATION, "Juma", start, end)
    payout = signed_by_the_clan(clan)
    step = app("open_payout", payout_id=payout["id"])
    assert step["step"] == "review"
    shown = {"txid": step["review"]["txid"], "total_sats": step["review"]["total_sats"]}
    return app, payout, step["review"], shown


def test_unread_alarms_come_before_approvals(clan, tmp_path, monkeypatch):
    home = tmp_path / "laptop"
    app, payout, _, shown = ready_to_approve(clan, home, monkeypatch)
    afribit_only_alarm(clan)
    (alarm,) = app("overview")["alarms"]
    assert alarm["kind"] == "sweep_blocked"
    assert "Read them before approving" in app.refused(
        "approve", payout_id=payout["id"], passphrase=PASSPHRASE, shown=shown
    )
    assert app("mark_alarms_read", newest=alarm["created_at"]) == {"unread": 0}
    assert app("alarms") == [] and len(app("alarms", recent=True)) == 1
    assert app("approve", payout_id=payout["id"], passphrase=PASSPHRASE, shown=shown)["approved"]


def test_a_large_payout_needs_its_total_typed(clan, tmp_path, monkeypatch):
    home = tmp_path / "laptop"
    register = ov.load_register(home)
    register["settings"]["large_payout_sats"] = 1
    ov.save_register(home, register)
    app, payout, review, shown = ready_to_approve(clan, home, monkeypatch)
    assert review["large"] is True
    for typed in (None, "1"):
        assert "isn't the total" in app.refused(
            "approve", payout_id=payout["id"], passphrase=PASSPHRASE, shown=shown, typed_total=typed
        )
    typed = f"{review['total_sats']:,}"
    reply = app(
        "approve", payout_id=payout["id"], passphrase=PASSPHRASE, shown=shown, typed_total=typed
    )
    assert reply["approved"]


def test_the_funding_address_comes_from_the_laptops_own_record(clan, tmp_path, monkeypatch):
    home = tmp_path / "laptop"
    app, *_ = ready_to_approve(clan, home, monkeypatch)
    (listed,) = app("clans")
    assert listed["clan_id"] == clan["cid"]
    assert listed["wallet_code"] == clan["policy"].wallet_code()
    found = app("funding_address", clan_id=clan["cid"])
    assert found["address"] == ov.clan_address(home, clan["cid"])
    assert found["address"][len(found["fixed_start"]) :].startswith(found["check_start"])
    assert found["address"].endswith(found["check_end"])
    assert guide.token_hash(home) in app("admin_lines")["text"]


def test_a_laptop_the_administrator_hasnt_added_says_so(clan, tmp_path, monkeypatch):
    home = tmp_path / "laptop"
    app = App(home)
    app("restore_key", words=WORDS, passphrase=PASSPHRASE)
    app("connect")
    laptop_on_clans(clan, home, monkeypatch)
    seen = app("overview")
    assert seen["answered"] is False and seen["reason"] == "not_added"


def test_requests_the_app_shouldnt_send_are_refused(tmp_path):
    app = App(tmp_path / "laptop")
    core = app.core
    assert service.handle(core, "not json")["code"] == "refused"
    assert service.handle(core, "[1]")["code"] == "refused"
    assert service.handle(core, json.dumps({"id": 1, "command": "sign"}))["code"] == "refused"
    assert service.handle(core, json.dumps({"id": 1, "command": "_fetch"}))["code"] == "refused"
    assert "Unexpected" in app.refused("status", extra=1)
    assert "needs payout_id" in app.refused("open_payout")
    assert "valid id" in app.refused("open_payout", payout_id="../../etc")
    assert "whole number" in app.refused(
        "register_wallet", clan_id="c1", generation=True, code="abcd"
    )
    assert "too long" in service.handle(core, "x" * (service.MAX_LINE + 1))["error"]
    assert "Open the payout first" in app.refused(
        "confirm_address", payout_id="p1", line=0, characters="a" * 12
    )


def test_only_answers_reach_the_app(tmp_path, monkeypatch, capsys):
    core = service.Service(tmp_path / "laptop")

    def chatty():
        print("this goes to stderr in the real app")
        return {"protocol": service.PROTOCOL}

    monkeypatch.setattr(core, "status", chatty)
    monkeypatch.setattr("sys.stdout", io.StringIO())
    answers = io.StringIO()
    requests = io.StringIO('{"id": 7, "command": "status"}\n\n{"id": 8, "command": "nope"}\n')
    service.serve(core, requests, answers)
    lines = [json.loads(line) for line in answers.getvalue().splitlines()]
    assert [(line["id"], line["ok"]) for line in lines] == [(7, True), (8, False)]


def run_core(home, *requests):
    """Starts the core as the desktop shell does and sends it request lines."""
    lines = "".join(json.dumps(request) + "\n" for request in requests)
    done = subprocess.run(
        [sys.executable, "-m", "clans.oversight_service", "--home", str(home), "--url", ORIGIN],
        input=lines,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        env={**os.environ, "PYTHONPATH": str(Path(service.__file__).parents[1])},
    )
    assert done.returncode == 0, done.stderr
    return [json.loads(line) for line in done.stdout.splitlines()]


def test_the_core_answers_one_line_per_request(tmp_path):
    first, second = run_core(
        tmp_path / "laptop",
        {"id": 1, "command": "status"},
        {"id": 2, "command": "create_key", "args": {"passphrase": "Ã©" * 12}},
    )
    assert first["ok"] and first["result"]["default_server"] == ORIGIN
    assert second["ok"] and len(second["result"]["words"]) == 12


def test_only_one_app_works_on_a_laptop_at_a_time(tmp_path, monkeypatch):
    home = tmp_path / "laptop"
    with ov.only_one_app(home):
        (answer,) = run_core(home, {"id": 1, "command": "status"})
        assert answer == {
            "id": 1,
            "ok": False,
            "error": answer["error"],
            "code": "check",
        }
        assert "already open" in answer["error"]
        monkeypatch.setattr("builtins.input", lambda prompt="": "")
        assert guide.run(home, ORIGIN) == 1
    (answer,) = run_core(home, {"id": 1, "command": "status"})
    assert answer["ok"]


def reason(app, command, **args):
    answer = app.answer(command, **args)
    assert not answer["ok"], answer
    return answer.get("reason")


def test_failed_checks_say_which_check_failed(clan, tmp_path, monkeypatch):
    home = tmp_path / "laptop"
    app, payout, review, shown = ready_to_approve(clan, home, monkeypatch)
    assert review["network"] == clan["policy"].network
    approve = {"payout_id": payout["id"], "shown": shown}
    calls = []
    real = ov.server
    monkeypatch.setattr(ov, "server", lambda home: calls.append(1) or real(home))
    assert reason(app, "approve", passphrase="not the passphrase", **approve) == "wrong_passphrase"
    assert calls == []  # a typing mistake doesn't use up the server's rate limit
    changed = {**approve, "shown": {**shown, "total_sats": shown["total_sats"] + 1}}
    assert reason(app, "approve", passphrase=PASSPHRASE, **changed) == "payout_changed"
    afribit_only_alarm(clan)
    assert app("open_payout", payout_id=payout["id"])["unread_alarms"] == 1
    assert reason(app, "approve", passphrase=PASSPHRASE, **approve) == "alarms_unread"
    assert reason(app, "restore_key", words="one two three", passphrase=PASSPHRASE) == "bad_words"
    assert reason(app, "open_payout", payout_id="not-waiting") == "payout_gone"


def test_the_paper_words_can_be_checked_again(tmp_path):
    app = App(tmp_path / "laptop")
    words = app("create_key", passphrase=PASSPHRASE)["words"]
    right = {"3": words[2], "11": words[10].upper()}
    assert app("check_words", passphrase=PASSPHRASE, answers=right) == {
        "matches": True,
        "wrong": [],
    }
    wrong = {"3": words[2], "7": "nope"}
    assert app("check_words", passphrase=PASSPHRASE, answers=wrong)["wrong"] == [7]
    assert reason(app, "check_words", passphrase="not the passphrase", answers=right) == (
        "wrong_passphrase"
    )
    assert "number" in app.refused("check_words", passphrase=PASSPHRASE, answers={"13": "x"})


def test_wallet_code_and_address_readings_say_when_they_differ(clan, tmp_path, monkeypatch):
    home = tmp_path / "laptop"
    app = set_up(clan, home, monkeypatch)
    payout = signed_by_the_clan(clan)
    app("open_payout", payout_id=payout["id"])
    wrong_code = {"clan_id": clan["cid"], "generation": 1, "code": "wrongcod"}
    assert reason(app, "register_wallet", **wrong_code) == "code_mismatch"
    assert ov.load_register(home)["wallets"] == {}
    code = clan["policy"].wallet_code()
    app("register_wallet", clan_id=clan["cid"], generation=1, code=code)
    app("open_payout", payout_id=payout["id"])
    start, end = ov.check_characters(DESTINATION)
    line = {"payout_id": payout["id"], "line": 0}
    assert reason(app, "confirm_address", characters="aaaaaabbbbbb", **line) == "address_mismatch"
    # People read bech32 addresses in capitals or not; both are the same address.
    app("confirm_address", characters=(start + end).upper(), **line)
    assert DESTINATION in ov.load_register(home)["addresses"]
    assert app("overview")["networks"] == [clan["policy"].network]
