"""The phone-side signer (frontend/src/vault) must agree with the backend wallet (BDK)."""

import json
import shutil
import subprocess
from pathlib import Path

import bdkpython as bdk
import pytest
from clan_wallet_helpers import (
    DESTINATION,
    OTHER_DESTINATION,
    fund,
    make_policy,
    secret_key,
    sign_normal_path,
)

from clans.clan_wallet import ClanPolicy, ClanWallet, ClanWalletError, Recipient

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(
    not NODE or not (FRONTEND / "node_modules" / "@scure" / "btc-signer").is_dir(),
    reason="Node.js and frontend dependencies are needed for the interoperability check",
)


def words(seed: int) -> str:
    return str(bdk.Mnemonic.from_entropy(bytes([seed]) * 16))


def policy_case(policy) -> dict:
    return {
        "network": policy.network,
        "oversight": [str(key) for key in policy.oversight],
        "signers": [str(key) for key in policy.signers],
        "recoveryThreshold": policy.recovery_threshold,
        "recoveryBlocks": policy.recovery_blocks,
    }


def run_phone_side(case: dict, tmp_path: Path) -> dict:
    path = tmp_path / "case.json"
    path.write_text(json.dumps(case), encoding="utf-8")
    result = subprocess.run(
        [NODE, "--no-warnings", "scripts/clan-wallet-interop.ts", str(path)],
        cwd=FRONTEND,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_phone_and_backend_build_the_same_wallet_and_signatures(tmp_path):
    keys = [secret_key(seed) for seed in range(1, 6)]
    policy = make_policy(keys)
    wallet = ClanWallet(policy)
    fund(wallet, 100_000)
    recipients = [Recipient(DESTINATION, 40_000)]
    draft = wallet.build_payout(
        recipients, fee_rate_sat_vb=2, max_fee_sats=2_000, allow_unconfirmed=True
    )
    redirected = wallet.build_payout(
        [Recipient(OTHER_DESTINATION, 40_000)],
        fee_rate_sat_vb=2,
        max_fee_sats=2_000,
        allow_unconfirmed=True,
    ).psbt
    other_clan = ClanWallet(make_policy(keys[1:]))
    fund(other_clan, 100_000)
    foreign = other_clan.build_payout(
        recipients, fee_rate_sat_vb=2, max_fee_sats=2_000, allow_unconfirmed=True
    ).psbt

    phone = run_phone_side(
        {
            "policy": policy_case(policy),
            # Signatories 1 and 2 sign on their phones; the oversight key signs separately.
            "words": [words(2), words(3)],
            "psbt": draft.psbt,
            "recipients": [{"address": r.address, "amountSats": r.amount_sats} for r in recipients],
            "maxFeeSats": 2_000,
            "tampered": {"redirected": redirected, "otherWallet": foreign},
        },
        tmp_path,
    )

    # Same keys from the same backup words, same wallet, same addresses.
    assert phone["keys"] == [str(policy.signers[0]), str(policy.signers[1])]
    assert phone["unspendableKey"] == policy.unspendable_key()
    assert phone["descriptors"] == {
        "external": policy.descriptor("external"),
        "internal": policy.descriptor("internal"),
    }
    assert phone["walletCode"] == policy.wallet_code()
    assert phone["addresses"] == [wallet.address(index) for index in range(3)]
    assert phone["changeAddresses"][0] == str(
        wallet.wallet.peek_address(bdk.KeychainKind.INTERNAL, 0).address
    )
    assert phone["review"]["feeSats"] == draft.fee_sats

    # The phone refuses anything that differs from the approved payout.
    refusals = phone["refusals"]
    assert "not approved" in refusals["redirected"] or "missing" in refusals["redirected"]
    assert "does not belong" in refusals["otherWallet"]
    assert "fee" in refusals["lowFeeLimit"]
    assert refusals["wrongAmount"]
    assert "do not belong" in refusals["outsider"]

    # Phone signatures plus the separately held oversight signature complete the payment.
    oversight = sign_normal_path(policy, keys[0], draft.psbt)
    signed = wallet.finalize(
        draft.psbt, [*phone["signed"], oversight], recipients, max_fee_sats=2_000
    )
    assert signed.txid == draft.txid

    # Two phone signatures without the oversight key are not enough.
    with pytest.raises(ClanWalletError, match="required signatures"):
        wallet.finalize(draft.psbt, phone["signed"], recipients, max_fee_sats=2_000)


def test_phone_checks_a_payout_where_the_beneficiary_pays_the_fee(tmp_path):
    keys = [secret_key(seed) for seed in range(1, 6)]
    policy = make_policy(keys)
    wallet = ClanWallet(policy)
    fund(wallet, 100_000)
    recipients = [Recipient(DESTINATION, 40_000)]
    options = {"fee_rate_sat_vb": 2, "max_fee_sats": 2_000, "allow_unconfirmed": True}
    draft = wallet.build_payout(recipients, fee_paid_by="recipients", **options)
    clan_pays = wallet.build_payout(recipients, **options).psbt
    case = {
        "policy": policy_case(policy),
        "words": [words(2), words(3)],
        "psbt": draft.psbt,
        "recipients": [{"address": DESTINATION, "amountSats": 40_000}],
        "maxFeeSats": 2_000,
        "feePaidBy": "recipients",
        # Paying the full amount (clan pays the fee) is not what was approved here.
        "tampered": {"clanPays": clan_pays},
    }
    phone = run_phone_side(case, tmp_path)
    assert phone["review"]["feeSats"] == draft.fee_sats
    assert phone["refusals"]["clanPays"]
    oversight = sign_normal_path(policy, keys[0], draft.psbt)
    signed = wallet.finalize(
        draft.psbt,
        [*phone["signed"], oversight],
        recipients,
        max_fee_sats=2_000,
        fee_paid_by="recipients",
    )
    assert signed.txid == draft.txid


def test_phone_and_backend_agree_with_two_oversight_keys(tmp_path):
    keys = [secret_key(seed) for seed in range(1, 7)]
    oversight = [str(keys[0].as_public()), str(keys[5].as_public())]
    policy = ClanPolicy.create(
        network="signet",
        oversight=oversight,
        signers=[str(key.as_public()) for key in keys[1:4]],
    )
    wallet = ClanWallet(policy)
    fund(wallet, 100_000)
    recipients = [Recipient(DESTINATION, 40_000)]
    draft = wallet.build_payout(
        recipients, fee_rate_sat_vb=2, max_fee_sats=2_000, allow_unconfirmed=True
    )
    phone = run_phone_side(
        {
            "policy": policy_case(policy),
            "words": [words(2), words(3)],
            "psbt": draft.psbt,
            "recipients": [{"address": DESTINATION, "amountSats": 40_000}],
            "maxFeeSats": 2_000,
            "tampered": {},
        },
        tmp_path,
    )
    assert phone["descriptors"]["external"] == policy.descriptor("external")
    assert phone["walletCode"] == policy.wallet_code()
    assert phone["addresses"] == [wallet.address(index) for index in range(3)]
    # The second Afribit key alone completes the payment with the phones.
    second = sign_normal_path(policy, keys[5], draft.psbt)
    signed = wallet.finalize(draft.psbt, [*phone["signed"], second], recipients, max_fee_sats=2_000)
    assert signed.txid == draft.txid


def test_phone_checks_a_move_to_the_clans_new_wallet(tmp_path):
    keys = [secret_key(seed) for seed in range(1, 7)]
    old_policy = make_policy(keys)
    # The third signatory's phone was stolen; the new wallet has their new key instead.
    new_policy = make_policy([*keys[:3], keys[5]])
    old, new = ClanWallet(old_policy), ClanWallet(new_policy)
    fund(old, 60_000, 0)
    fund(old, 40_000, 1)
    coins = [utxo.outpoint for utxo in old.wallet.list_unspent()]
    destination = new.change_address(0)
    options = {"fee_rate_sat_vb": 2, "max_fee_sats": 10_000}
    move = old.build_sweep(coins, destination, **options)
    redirected = old.build_sweep(coins, OTHER_DESTINATION, **options)
    back_to_old = old.build_sweep(coins, old.change_address(0), **options)
    grant = old.build_payout(
        [Recipient(DESTINATION, 40_000)],
        fee_rate_sat_vb=2,
        max_fee_sats=2_000,
        allow_unconfirmed=True,
    )
    phone = run_phone_side(
        {
            "policy": policy_case(old_policy),
            "words": [words(2), words(3)],
            "psbt": move.psbt,
            "recipients": [],
            "maxFeeSats": 10_000,
            "tampered": {
                "redirected": redirected.psbt,
                "backToOld": back_to_old.psbt,
                "grant": grant.psbt,
            },
            "sweep": {"destination": policy_case(new_policy), "index": 0},
        },
        tmp_path,
    )
    assert phone["review"] == {
        "feeSats": move.fee_sats,
        "amountSats": move.amount_sats,
        "address": destination,
        "inputs": 2,
    }
    refusals = phone["refusals"]
    assert "not approved" in refusals["redirected"]
    assert "not approved" in refusals["backToOld"]
    assert "one clan address" in refusals["grant"]
    assert "fee" in refusals["lowFeeLimit"]
    assert "not approved" in refusals["wrongIndex"]
    assert "does not belong" in refusals["wrongSource"]
    assert "do not belong" in refusals["outsider"]

    # Two phones plus Afribit's key complete the move.
    oversight = sign_normal_path(old_policy, keys[0], move.psbt)
    signed = old.finalize_sweep(
        move.psbt, [*phone["signed"], oversight], destination, max_fee_sats=10_000
    )
    assert signed.txid == move.txid


def test_phone_checks_a_refresh_back_to_the_same_wallet(tmp_path):
    keys = [secret_key(seed) for seed in range(1, 6)]
    policy = make_policy(keys)
    wallet = ClanWallet(policy)
    fund(wallet, 80_000)
    coins = [utxo.outpoint for utxo in wallet.wallet.list_unspent()]
    destination = wallet.change_address(2)
    refresh = wallet.build_sweep(coins, destination, fee_rate_sat_vb=2, max_fee_sats=10_000)
    phone = run_phone_side(
        {
            "policy": policy_case(policy),
            "words": [words(3), words(4)],
            "psbt": refresh.psbt,
            "recipients": [],
            "maxFeeSats": 10_000,
            "tampered": {},
            "sweep": {"destination": policy_case(policy), "index": 2},
        },
        tmp_path,
    )
    assert phone["review"]["address"] == destination
    assert phone["review"]["amountSats"] == 80_000 - refresh.fee_sats
    oversight = sign_normal_path(policy, keys[0], refresh.psbt)
    signed = wallet.finalize_sweep(
        refresh.psbt, [*phone["signed"], oversight], destination, max_fee_sats=10_000
    )
    assert signed.txid == refresh.txid


def test_phone_and_backend_agree_on_a_mainnet_wallet(tmp_path):
    from test_mainnet import DESTINATION as MAIN_DESTINATION
    from test_mainnet import fund as fund_mainnet
    from test_mainnet import main_key, sign_as

    from clans import recover

    keys = [main_key(seed) for seed in range(1, 5)]
    policy = ClanPolicy.create(
        network="bitcoin",
        oversight=str(keys[0].as_public()),
        signers=[str(key.as_public()) for key in keys[1:]],
    )
    wallet = ClanWallet(policy)
    fund_mainnet(wallet, 100_000)
    recipients = [Recipient(MAIN_DESTINATION, 40_000)]
    draft = wallet.build_payout(
        recipients, fee_rate_sat_vb=2, max_fee_sats=2_000, allow_unconfirmed=True
    )
    phone = run_phone_side(
        {
            "policy": policy_case(policy),
            "words": [words(2), words(3)],
            "psbt": draft.psbt,
            "recipients": [{"address": MAIN_DESTINATION, "amountSats": 40_000}],
            "maxFeeSats": 2_000,
            "tampered": {},
        },
        tmp_path,
    )
    assert phone["keys"] == [str(policy.signers[0]), str(policy.signers[1])]
    assert phone["keys"][0] == str(recover.account_key(words(2), "bitcoin").as_public())
    assert phone["unspendableKey"] == policy.unspendable_key()
    assert phone["walletCode"] == policy.wallet_code()
    assert phone["addresses"] == [wallet.address(index) for index in range(3)]
    assert phone["addresses"][0].startswith("bc1p")
    assert "do not belong" in phone["refusals"]["outsider"]
    signed = wallet.finalize(
        draft.psbt,
        [*phone["signed"], sign_as(policy, keys[0], draft.psbt)],
        recipients,
        max_fee_sats=2_000,
    )
    assert signed.txid == draft.txid
