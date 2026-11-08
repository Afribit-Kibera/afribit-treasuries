"""The recovery path: signatories alone move a clan's money, without Clans or Afribit."""

import json

import bdkpython as bdk
import pytest
from clan_wallet_helpers import DESTINATION, OTHER_DESTINATION, fund, make_policy, secret_key

from clans import recover
from clans.clan_wallet import ClanWallet
from clans.recover import RecoveryError

WAIT = 4_320


def words(seed: int) -> str:
    """The 12 words behind test key `seed` (see clan_wallet_helpers.secret_key)."""
    return str(bdk.Mnemonic.from_entropy(bytes([seed]) * 16))


@pytest.fixture
def policy():
    # Oversight is key 1; signatories hold keys 2-4; 2 of them can recover.
    return make_policy([secret_key(seed) for seed in range(1, 5)], recovery_blocks=WAIT)


@pytest.fixture
def wallet(policy):
    wallet = ClanWallet(policy)
    fund(wallet, 50_000, 0)
    fund(wallet, 30_000, 3)
    return wallet


def sweep_of(policy, wallet, to=DESTINATION):
    every = [c.outpoint for c in recover.coins(policy, wallet, tip=0)]
    return recover.build_sweep(policy, wallet, to, every, fee_rate_sat_vb=2)


def test_the_backup_rebuilds_the_same_wallet(policy):
    backup = recover.wallet_backup(policy, generation=2, clan_id="c1")
    assert backup["wallet_code"] == policy.wallet_code()
    # Phones write the descriptor text the API documents, followed by its checksum.
    for keychain in ("external", "internal"):
        text, checksum = backup["descriptors"][keychain].rsplit("#", 1)
        assert text == policy.descriptor(keychain) and len(checksum) == 8
    copy = recover.read_backup(json.loads(json.dumps(backup)))
    assert copy == policy
    assert ClanWallet(copy).address(0) == ClanWallet(policy).address(0)


@pytest.mark.parametrize(
    "change",
    [
        {"format": "something-else"},
        {"wallet_code": "abcdefgh"},
        {"threshold": 3},
        {"recovery_blocks": WAIT + 1},
        {"signers": None},
    ],
)
def test_a_damaged_backup_is_refused(policy, change):
    backup = {**recover.wallet_backup(policy), **change}
    with pytest.raises(RecoveryError):
        recover.read_backup(backup)


def test_a_backup_with_a_swapped_key_is_refused(policy):
    backup = recover.wallet_backup(policy)
    backup["signers"][0] = str(secret_key(9).as_public())
    with pytest.raises(RecoveryError, match="doesn't match"):
        recover.read_backup(backup)


def test_bitcoin_core_gets_a_watch_only_copy(policy):
    request = recover.core_import(policy)
    assert [item["internal"] for item in request] == [False, True]
    assert all("tprv" not in item["desc"] and "#" in item["desc"] for item in request)


def test_coins_wait_for_the_recovery_period(policy, wallet):
    found = recover.coins(policy, wallet, tip=500)
    assert sorted(c.amount_sats for c in found) == [30_000, 50_000]
    # Unconfirmed coins have the full wait ahead of them.
    assert all(c.waiting_blocks == WAIT and not c.recoverable for c in found)


def test_two_signatories_recover_without_afribit(policy, wallet):
    sweep = sweep_of(policy, wallet)
    checked = recover.check_sweep(policy, sweep)
    assert checked.amount_sats == 80_000 - checked.fee_sats and checked.to == DESTINATION
    tx = bdk.Psbt(sweep["psbt"]).extract_tx_unchecked_fee_rate()
    # Every coin carries the recovery wait, so the network only accepts it once it has passed.
    assert [txin.sequence for txin in tx.input()] == [WAIT, WAIT]
    first = recover.sign_sweep(policy, sweep, words(2))
    with pytest.raises(RecoveryError, match="2 signatories"):
        recover.finish_sweep(policy, sweep, [first])
    second = recover.sign_sweep(policy, sweep, words(4))
    raw = recover.finish_sweep(policy, sweep, [first, second])
    sent = bdk.Transaction(bytes.fromhex(raw))
    assert str(sent.compute_txid()) == checked.txid
    assert [o.value.to_sat() for o in sent.output()] == [checked.amount_sats]


def test_afribit_cannot_use_the_recovery_path(policy, wallet):
    sweep = sweep_of(policy, wallet)
    with pytest.raises(RecoveryError, match="don't belong to a signatory"):
        recover.sign_sweep(policy, sweep, words(1))
    with pytest.raises(RecoveryError, match="don't belong to a signatory"):
        recover.sign_sweep(policy, sweep, words(9))
    with pytest.raises(RecoveryError, match="aren't valid"):
        recover.sign_sweep(policy, sweep, "not twelve real words")


def test_a_changed_sweep_is_refused_before_signing(policy, wallet):
    sweep = sweep_of(policy, wallet)
    other = sweep_of(policy, wallet, to=OTHER_DESTINATION)
    # The file says one address while the payment pays another.
    with pytest.raises(RecoveryError, match="one agreed address"):
        recover.check_sweep(policy, {**other, "to": DESTINATION})
    with pytest.raises(RecoveryError, match="different clan wallet"):
        recover.check_sweep(policy, {**sweep, "wallet_code": "abcdefgh"})
    with pytest.raises(RecoveryError, match="above the limit"):
        recover.check_sweep(policy, sweep, max_fee_sats=10)
    stranger = make_policy([secret_key(seed) for seed in (5, 6, 7, 8)], recovery_blocks=WAIT)
    with pytest.raises(RecoveryError):
        recover.check_sweep(stranger, sweep)


def test_a_normal_payment_is_not_a_recovery_sweep(policy, wallet):
    from clans.clan_wallet import Recipient

    draft = wallet.build_payout(
        [Recipient(DESTINATION, 70_000)],
        fee_rate_sat_vb=2,
        max_fee_sats=3_000,
        allow_unconfirmed=True,
    )
    fake = {**sweep_of(policy, wallet), "psbt": draft.psbt}
    with pytest.raises(RecoveryError):
        recover.check_sweep(policy, fake)


def test_signed_copies_of_another_sweep_are_refused(policy, wallet):
    sweep = sweep_of(policy, wallet)
    other = sweep_of(policy, wallet, to=OTHER_DESTINATION)
    first = recover.sign_sweep(policy, sweep, words(2))
    stray = recover.sign_sweep(policy, other, words(3))
    with pytest.raises(RecoveryError, match="different sweep"):
        recover.finish_sweep(policy, sweep, [first, stray])
    with pytest.raises(RecoveryError, match="different sweep"):
        recover.finish_sweep(policy, sweep, [first, {**stray, "txid": first["txid"]}])


def test_the_command_line_checks_signs_and_finishes(policy, wallet, tmp_path, monkeypatch, capsys):
    backup = tmp_path / "backup.json"
    backup.write_text(json.dumps(recover.wallet_backup(policy)), encoding="utf-8")
    assert recover.main(["check", str(backup)]) == 0
    assert policy.wallet_code() in capsys.readouterr().out
    sweep = tmp_path / "sweep.json"
    sweep.write_text(json.dumps(sweep_of(policy, wallet)), encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda _: "wrong!")
    monkeypatch.setattr(recover.getpass, "getpass", lambda _: words(2))
    assert recover.main(["sign", str(backup), str(sweep), "--out", str(tmp_path / "a")]) == 1
    assert not (tmp_path / "a").exists()
    monkeypatch.setattr("builtins.input", lambda _: DESTINATION[-6:])
    for seed, name in ((2, "a"), (3, "b")):
        monkeypatch.setattr(recover.getpass, "getpass", lambda _, s=seed: words(s))
        out = str(tmp_path / name)
        assert recover.main(["sign", str(backup), str(sweep), "--out", out]) == 0
        assert "tprv" not in (tmp_path / name).read_text(encoding="utf-8")
    capsys.readouterr()
    paths = [str(tmp_path / "a"), str(tmp_path / "b")]
    assert recover.main(["finish", str(backup), str(sweep), *paths]) == 0
    assert "Ready to send" in capsys.readouterr().out
    damaged = tmp_path / "damaged.json"
    damaged.write_text("{}", encoding="utf-8")
    assert recover.main(["check", str(damaged)]) == 1
