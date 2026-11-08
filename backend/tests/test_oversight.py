"""The Afribit oversight tool signs only payouts that match the laptop's own records."""

import json

import bdkpython as bdk
import pytest
from clan_wallet_helpers import (
    DESTINATION,
    OTHER_DESTINATION,
    fund,
    secret_key,
    sign_normal_path,
)

from clans import oversight
from clans.clan_wallet import ClanPolicy, ClanWallet, Recipient
from clans.oversight import OversightError

PASSPHRASE = "correct horse battery staple"
WORDS = str(bdk.Mnemonic.from_entropy(bytes([9]) * 16))


@pytest.fixture
def home(tmp_path):
    oversight.create_key(tmp_path, PASSPHRASE, WORDS)
    return tmp_path


@pytest.fixture
def clan(home):
    """A 3-signatory clan whose wallet includes this laptop's oversight key."""
    signers = [secret_key(seed) for seed in (1, 2, 3)]
    policy = ClanPolicy.create(
        network="signet",
        oversight=[oversight.public_key(home)],
        signers=[str(key.as_public()) for key in signers],
    )
    view = {
        "generation": 1,
        "policy": {
            "network": "signet",
            "oversight": [str(key) for key in policy.oversight],
            "signers": [str(key) for key in policy.signers],
            "recovery_threshold": policy.recovery_threshold,
            "recovery_blocks": policy.recovery_blocks,
        },
    }
    wallet = ClanWallet(policy)
    fund(wallet, 200_000)
    return policy, view, wallet, signers


def register_clan(home, view, policy):
    oversight.add_wallet(home, "clan-1", view, policy.wallet_code())


def confirm(home, address, name="Amina"):
    start, end = oversight.check_characters(address)
    oversight.confirm_address(home, address, name, start, end)


def payout(policy, wallet, signers, recipients, *, grant_ids=None, fee_rate=2, sign=True):
    draft = wallet.build_payout(
        recipients,
        fee_rate_sat_vb=fee_rate,
        max_fee_sats=3_000,
        allow_unconfirmed=True,
        fee_paid_by="recipients",
    )
    psbt = draft.psbt
    if sign:
        combined = bdk.Psbt(psbt)
        for key in signers[:2]:
            combined = combined.combine(bdk.Psbt(sign_normal_path(policy, key, psbt)))
        psbt = combined.serialize()
    return {
        "clan_id": "clan-1",
        "psbt": psbt,
        "fee_paid_by": "recipients",
        "max_fee_sats": 3_000,
        "recipients": [
            {
                "grant_id": (grant_ids or [f"grant-{i}" for i in range(len(recipients))])[i],
                "name": f"Beneficiary {i}",
                "address": r.address,
                "approved_sats": r.amount_sats,
            }
            for i, r in enumerate(recipients)
        ],
    }


def test_key_is_encrypted_and_restorable(tmp_path, home):
    record = (home / oversight.KEY_FILE).read_text(encoding="utf-8")
    assert WORDS.split()[0] not in record and PASSPHRASE not in record
    public = oversight.public_key(home)
    assert str(oversight.unlock(home, PASSPHRASE).as_public()) == public
    with pytest.raises(OversightError, match="Wrong passphrase"):
        oversight.unlock(home, "not the passphrase")
    with pytest.raises(OversightError, match="already has an oversight key"):
        oversight.create_key(home, PASSPHRASE)
    with pytest.raises(OversightError, match="at least 12"):
        oversight.create_key(tmp_path / "other", "short")
    _, restored = oversight.create_key(tmp_path / "restored", "another long passphrase", WORDS)
    assert restored == public
    words, fresh = oversight.create_key(tmp_path / "fresh", PASSPHRASE)
    assert len(words.split()) == 12 and fresh != public


def test_wallet_registration_needs_the_phone_code_and_this_key(home, clan):
    policy, view, _, signers = clan
    with pytest.raises(OversightError, match="doesn't match the signatory's phone"):
        oversight.add_wallet(home, "clan-1", view, "aaaaaaaa")
    other = ClanPolicy.create(
        network="signet",
        oversight=[str(secret_key(7).as_public())],
        signers=[str(key.as_public()) for key in signers],
    )
    foreign = {"policy": view["policy"] | {"oversight": [str(other.oversight[0])]}}
    with pytest.raises(OversightError, match="doesn't include this laptop"):
        oversight.add_wallet(home, "clan-1", foreign, other.wallet_code())
    register_clan(home, view, policy)
    # A different wallet for the same clan needs a new generation.
    changed = ClanPolicy.create(
        network="signet",
        oversight=[oversight.public_key(home)],
        signers=[str(secret_key(seed).as_public()) for seed in (1, 2, 4)],
    )
    swapped = {
        "generation": 1,
        "policy": view["policy"] | {"signers": [str(key) for key in changed.signers]},
    }
    with pytest.raises(OversightError, match="new generation"):
        oversight.add_wallet(home, "clan-1", swapped, changed.wallet_code())
    oversight.add_wallet(home, "clan-1", swapped | {"generation": 2}, changed.wallet_code())


def test_address_must_be_read_back_by_the_beneficiary(home):
    start, end = oversight.check_characters(DESTINATION)
    assert DESTINATION[4:10] == start and DESTINATION.endswith(end)
    with pytest.raises(OversightError, match="don't match"):
        oversight.confirm_address(home, DESTINATION, "Amina", start, "zzzzzz")
    with pytest.raises(OversightError, match="valid address"):
        oversight.confirm_address(home, "bc1qnotanaddress", "Amina", start, end)
    oversight.confirm_address(home, DESTINATION, "Amina", start, end)
    assert DESTINATION in oversight.load_register(home)["addresses"]


def test_signs_a_matching_payout_and_completes_it(home, clan):
    policy, view, wallet, signers = clan
    register_clan(home, view, policy)
    confirm(home, DESTINATION)
    request = payout(policy, wallet, signers, [Recipient(DESTINATION, 40_000)])
    checked = oversight.review(home, request)
    assert checked.total_sats == 40_000
    assert checked.lines[0][3] == 40_000 - checked.fee_sats
    signed, complete = oversight.sign(home, request, PASSPHRASE)
    assert complete
    finished = wallet.finalize(
        request["psbt"],
        [signed],
        [Recipient(DESTINATION, 40_000)],
        max_fee_sats=3_000,
        fee_paid_by="recipients",
    )
    assert finished.txid == checked.txid
    # Signing the same payment again is harmless and not recorded twice.
    oversight.sign(home, request, PASSPHRASE)
    assert len(oversight.load_register(home)["payouts"]) == 1


def test_signing_before_the_clan_is_allowed_but_not_complete(home, clan):
    policy, view, wallet, signers = clan
    register_clan(home, view, policy)
    confirm(home, DESTINATION)
    request = payout(policy, wallet, signers, [Recipient(DESTINATION, 40_000)], sign=False)
    _, complete = oversight.sign(home, request, PASSPHRASE)
    assert not complete


def test_refuses_payouts_that_differ_from_the_laptop_records(home, clan):
    policy, view, wallet, signers = clan
    request = payout(policy, wallet, signers, [Recipient(DESTINATION, 40_000)])
    with pytest.raises(OversightError, match="isn't registered"):
        oversight.review(home, request)
    register_clan(home, view, policy)
    with pytest.raises(OversightError, match="Confirm these addresses"):
        oversight.review(home, request)
    confirm(home, DESTINATION)
    # The server claims a different amount than the payment actually pays.
    inflated = json.loads(json.dumps(request))
    inflated["recipients"][0]["approved_sats"] = 30_000
    with pytest.raises(OversightError, match="do not match"):
        oversight.review(home, inflated)
    # The server raises its own fee limit; the laptop's limit still applies.
    oversight.save_register(
        home,
        oversight.load_register(home) | {"settings": {"max_fee_sats": 100, "large_payout_sats": 1}},
    )
    with pytest.raises(OversightError, match="fee is above"):
        oversight.review(home, request | {"max_fee_sats": 1_000_000})
    oversight.save_register(
        home, oversight.load_register(home) | {"settings": dict(oversight.DEFAULT_SETTINGS)}
    )
    with pytest.raises(OversightError, match="Wrong passphrase"):
        oversight.sign(home, request, "wrong passphrase!")
    # A payment to an address nobody confirmed is refused even if it is otherwise valid.
    redirected = payout(policy, wallet, signers, [Recipient(OTHER_DESTINATION, 40_000)])
    with pytest.raises(OversightError, match="Confirm these addresses"):
        oversight.sign(home, redirected, PASSPHRASE)
    assert oversight.load_register(home)["payouts"] == []


def test_a_grant_is_paid_once_but_can_be_bumped(home, clan):
    policy, view, wallet, signers = clan
    register_clan(home, view, policy)
    confirm(home, DESTINATION)
    confirm(home, OTHER_DESTINATION, "Juma")
    first = payout(policy, wallet, signers, [Recipient(DESTINATION, 40_000)], grant_ids=["g1"])
    oversight.sign(home, first, PASSPHRASE)
    # A higher-fee version spends the same coins, so it can replace the first.
    bumped = payout(
        policy, wallet, signers, [Recipient(DESTINATION, 40_000)], grant_ids=["g1"], fee_rate=5
    )
    assert oversight.review(home, bumped).replaces
    # The same grant paid from different coins would pay it twice.
    elsewhere = ClanWallet(policy)
    fund(elsewhere, 90_000, index=3)
    other_coins = payout(
        policy, elsewhere, signers, [Recipient(OTHER_DESTINATION, 85_000)], grant_ids=["g1"]
    )
    spent = set(oversight.load_register(home)["payouts"][0]["inputs"])
    assert not spent & set(oversight._inputs(bdk.Psbt(other_coins["psbt"])))
    with pytest.raises(OversightError, match="already paid"):
        oversight.review(home, other_coins)
    # A different grant from those coins is fine.
    other_coins["recipients"][0]["grant_id"] = "g2"
    assert not oversight.review(home, other_coins).replaces


def test_change_far_along_the_wallet_is_still_recognised(home, clan):
    policy, view, wallet, signers = clan
    for index in range(60):
        wallet.wallet.reveal_next_address(bdk.KeychainKind.INTERNAL)
        wallet.wallet.mark_used(bdk.KeychainKind.INTERNAL, index)
    register_clan(home, view, policy)
    confirm(home, DESTINATION)
    request = payout(policy, wallet, signers, [Recipient(DESTINATION, 40_000)])
    tx = bdk.Psbt(request["psbt"]).extract_tx_unchecked_fee_rate()
    change = [
        output
        for output in tx.output()
        if wallet.wallet.derivation_of_spk(output.script_pubkey) is not None
    ]
    assert wallet.wallet.derivation_of_spk(change[0].script_pubkey).index >= 50
    assert oversight.review(home, request).total_sats == 40_000


def test_clan_funding_address_comes_from_the_registered_wallet(home, clan):
    policy, view, wallet, _ = clan
    with pytest.raises(OversightError, match="isn't registered"):
        oversight.clan_address(home, "clan-1")
    register_clan(home, view, policy)
    assert oversight.clan_address(home, "clan-1") == wallet.address(0)
    assert oversight.clan_address(home, "clan-1", 5) == wallet.address(5)


def test_the_laptop_exports_the_clan_wallet_backup(home, clan, tmp_path):
    from clans import recover

    policy, view, _, _ = clan
    with pytest.raises(OversightError, match="isn't registered"):
        oversight.wallet_backup(home, "clan-1")
    register_clan(home, view, policy)
    out = tmp_path / "backup.json"
    args = ["--home", str(home), "export-backup", "--clan", "clan-1", "--out", str(out)]
    assert oversight.main(args) == 0
    backup = json.loads(out.read_text(encoding="utf-8"))
    assert backup["clan_id"] == "clan-1" and "tprv" not in out.read_text(encoding="utf-8")
    assert recover.read_backup(backup) == policy


def test_command_line_status(home, capsys):
    assert oversight.main(["--home", str(home), "show-key"]) == 0
    assert oversight.public_key(home, "bitcoin") in capsys.readouterr().out
    assert oversight.main(["--home", str(home), "show-key", "--network", "signet"]) == 0
    assert oversight.public_key(home) in capsys.readouterr().out
    assert oversight.main(["--home", str(home / "empty"), "status"]) == 2
    assert "no oversight key" in capsys.readouterr().err
