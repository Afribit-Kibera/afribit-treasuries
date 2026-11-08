"""The guided oversight app, driven the way a person would answer its questions."""

import json

import bdkpython as bdk
import test_clan_wallet_payments as payments
from clan_wallet_helpers import DESTINATION
from fastapi.testclient import TestClient
from test_clan_wallet_payments import ready_payout, sign, tick
from test_live_app import ORIGIN

from clans import oversight as ov
from clans import oversight_guide as guide

clan, keys = payments.clan, payments.keys

PASSPHRASE = "correct horse battery staple"
WORDS = str(bdk.Mnemonic.from_entropy(bytes([1]) * 16))  # the clan fixture's oversight key


class Person:
    """Answers each question from a script, and records what the app asked."""

    def __init__(self, monkeypatch, tmp_path, choices, answers):
        self.choices, self.answers, self.asked, self.words = list(choices), answers, [], None
        real_create = ov.create_key

        def create_key(*args):
            self.words, public = real_create(*args)
            return self.words, public

        monkeypatch.setattr(ov, "create_key", create_key)
        monkeypatch.setattr("builtins.input", self.input)
        monkeypatch.setattr(guide.getpass, "getpass", self.getpass)
        monkeypatch.setattr(guide, "clear_screen", lambda: None)
        monkeypatch.setattr(guide, "desktop", lambda: tmp_path)
        monkeypatch.setattr(guide, "copy_to_clipboard", lambda _: False)

    def input(self, prompt=""):
        self.asked.append(prompt)
        if "Type a number" in prompt:
            choice = self.choices.pop(0)
            return choice() if callable(choice) else choice
        if prompt.startswith("Word number"):
            number = int(prompt.split()[2].rstrip(":"))
            wrong = self.answers.get("wrong words", 0)
            if wrong:
                self.answers["wrong words"] = wrong - 1
                return "nope"
            return self.words.split()[number - 1]
        for start, answer in self.answers.items():
            if prompt.strip().startswith(start):
                return answer.pop(0) if isinstance(answer, list) else answer
        return ""

    def getpass(self, prompt=""):
        self.asked.append(prompt)
        return WORDS if "backup words" in prompt else PASSPHRASE


def test_a_new_key_is_made_only_after_the_words_are_written_down(tmp_path, monkeypatch):
    home = tmp_path / "laptop"
    person = Person(monkeypatch, tmp_path, ["6"], {"wrong words": 1})

    def not_added_yet(_):
        raise ov.OversightError("Clans refused this (401): unknown token")

    monkeypatch.setattr(ov, "server", not_added_yet)
    assert guide.run(home, "https://pilot.clans.example.org") == 0
    # A wrong word shows the words again, and the second check passes.
    assert sum(prompt.startswith("Word number") for prompt in person.asked) >= 3
    sent = (tmp_path / guide.ADMIN_FILE).read_text(encoding="utf-8")
    assert ov.public_key(home) in sent and guide.token_hash(home) in sent
    assert person.words not in sent and "token" not in sent.lower()
    saved = json.loads((home / ov.SERVER_FILE).read_text(encoding="utf-8"))
    assert saved["url"] == "https://pilot.clans.example.org"


def test_one_choice_goes_through_the_wallet_the_address_and_the_payout(
    clan, tmp_path, monkeypatch, capsys
):
    home = tmp_path / "laptop"
    settings = clan["app"].state.security.settings
    _, second, third = clan["signers"]
    _, payout = ready_payout(clan)
    sign(clan, third, sign(clan, second, payout).json())

    def laptop(_home):
        token = json.loads((home / ov.SERVER_FILE).read_text(encoding="utf-8"))["token"]
        headers = {"Authorization": "Bearer " + token}
        return TestClient(clan["app"], base_url=ORIGIN, headers=headers)

    monkeypatch.setattr(ov, "server", laptop)

    def administrator_adds_the_laptop():
        settings.clan_wallet_oversight_token_hashes = guide.token_hash(home)
        return "1"  # check again

    start, end = ov.check_characters(DESTINATION)
    code = clan["policy"].wallet_code()
    person = Person(
        monkeypatch,
        tmp_path,
        # Check again; Go through it; Clan address for funding; Close.
        [administrator_adds_the_laptop, "", "2", "6"],
        {
            "Press Enter to create": "r",
            "Wallet code they read": ["wrongcod", code[:4] + " " + code[4:]],
            "Type the 12 characters": start + " " + end,
        },
    )
    assert guide.run(home, ORIGIN) == 0
    assert ov.clan_address(home, clan["cid"]) in capsys.readouterr().out
    asked = "\n".join(person.asked)
    assert "Ask them to read it again" not in asked  # printed, not asked
    register = ov.load_register(home)
    assert register["wallets"][clan["cid"]]["clan_name"]
    assert DESTINATION in register["addresses"]
    assert ov.pending(laptop(home)) == []
    tick(clan)
    assert clan["chain"].broadcasts == [payout["txid"]]


def test_a_wrong_address_reading_stops_the_payout(clan, tmp_path, monkeypatch):
    home = tmp_path / "laptop"
    ov.create_key(home, PASSPHRASE, WORDS)
    view = clan["signers"][0].get(f"/api/clans/{clan['cid']}/wallet").json()
    ov.add_wallet(home, clan["cid"], view, clan["policy"].wallet_code())
    clan["app"].state.security.settings.clan_wallet_oversight_token_hashes = ov.connect(
        home, ORIGIN
    )
    _, second, third = clan["signers"]
    _, payout = ready_payout(clan)
    sign(clan, third, sign(clan, second, payout).json())
    token = json.loads((home / ov.SERVER_FILE).read_text(encoding="utf-8"))["token"]
    client = TestClient(clan["app"], base_url=ORIGIN, headers={"Authorization": "Bearer " + token})
    monkeypatch.setattr(ov, "server", lambda _: client)
    Person(
        monkeypatch,
        tmp_path,
        ["6"],  # opening goes straight to the payout; then Close
        {"Type the 12 characters": "aaaaaa bbbbbb"},
    )
    assert guide.run(home, ORIGIN) == 0
    assert DESTINATION not in ov.load_register(home)["addresses"]
    assert len(ov.pending(client)) == 1  # nothing was signed


def test_pressing_enter_at_the_passphrase_skips_the_payout(clan, tmp_path, monkeypatch):
    home = tmp_path / "laptop"
    ov.create_key(home, PASSPHRASE, WORDS)
    view = clan["signers"][0].get(f"/api/clans/{clan['cid']}/wallet").json()
    ov.add_wallet(home, clan["cid"], view, clan["policy"].wallet_code())
    clan["app"].state.security.settings.clan_wallet_oversight_token_hashes = ov.connect(
        home, ORIGIN
    )
    _, second, third = clan["signers"]
    _, payout = ready_payout(clan)
    sign(clan, third, sign(clan, second, payout).json())
    token = json.loads((home / ov.SERVER_FILE).read_text(encoding="utf-8"))["token"]
    client = TestClient(clan["app"], base_url=ORIGIN, headers={"Authorization": "Bearer " + token})
    monkeypatch.setattr(ov, "server", lambda _: client)
    start, end = ov.check_characters(DESTINATION)
    person = Person(monkeypatch, tmp_path, ["6"], {"Type the 12 characters": start + end})
    person.getpass = lambda prompt="": ""
    monkeypatch.setattr(guide.getpass, "getpass", person.getpass)
    assert guide.run(home, ORIGIN) == 0
    assert DESTINATION in ov.load_register(home)["addresses"]  # the check was kept
    assert len(ov.pending(client)) == 1  # but nothing was signed
