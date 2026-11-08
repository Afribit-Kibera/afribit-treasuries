"""Clan multisig wallets: setup rules, addresses and offline spending checks (test network)."""

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

from clans.clan_wallet import (
    ACCOUNT_PATH,
    ClanPolicy,
    ClanWallet,
    ClanWalletError,
    Recipient,
    amounts_received,
    fee_shares,
)


@pytest.fixture(scope="module")
def keys():
    return [secret_key(seed) for seed in range(1, 9)]


def test_policy_uses_oversight_and_majority(keys):
    for count, majority in ((3, 2), (5, 3), (7, 4)):
        policy = make_policy(keys, count)
        assert policy.threshold == majority
        descriptor = policy.descriptor("external")
        assert f"multi_a({majority}," in descriptor
        assert "older(26280)" in descriptor
        assert descriptor.startswith("tr(tpub")
        assert len(policy.wallet_code()) == 8


def test_each_wallet_has_its_own_unspendable_key(keys):
    first, second = make_policy(keys), make_policy(keys[1:])
    assert first.unspendable_key() != second.unspendable_key()
    assert first.unspendable_key() == make_policy(keys).unspendable_key()
    # The extended key wraps the BIP-341 point, so nobody can spend through the key path.
    parsed = bdk.DescriptorPublicKey.from_string(first.unspendable_key())
    assert parsed.is_multipath() is False
    assert first.descriptor("external").startswith(f"tr({first.unspendable_key()}/0/*,")
    assert first.descriptor("internal").startswith(f"tr({first.unspendable_key()}/1/*,")


@pytest.mark.parametrize(
    "change, message",
    [
        ({"signers": 4}, "3, 5 or 7"),
        ({"recovery_threshold": 1}, "majority"),
        ({"recovery_threshold": 4}, "majority"),
        ({"recovery_blocks": 100}, "recovery wait"),
        ({"recovery_blocks": 70_000}, "recovery wait"),
    ],
)
def test_policy_rejects_unsafe_setups(keys, change, message):
    with pytest.raises(ClanWalletError, match=message):
        make_policy(keys, **change)


def test_policy_rejects_reused_or_wrong_keys(keys):
    oversight = str(keys[0].as_public())
    with pytest.raises(ClanWalletError, match="different"):
        ClanPolicy.create(
            network="signet",
            oversight=oversight,
            signers=[oversight, str(keys[1].as_public()), str(keys[2].as_public())],
        )
    with pytest.raises(ClanWalletError, match="test networks"):
        ClanPolicy.create(
            network="bitcoin",
            oversight=oversight,
            signers=[str(key.as_public()) for key in keys[1:4]],
        )
    with pytest.raises(ClanWalletError, match="public key"):
        ClanPolicy.create(
            network="signet",
            oversight=oversight,
            signers=[str(keys[1]), str(keys[2].as_public()), str(keys[3].as_public())],
        )
    other_path = keys[1].as_public()
    wrong = str(other_path).replace(ACCOUNT_PATH, "84'/1'/0'")
    with pytest.raises(ClanWalletError, match="account path"):
        ClanPolicy.create(
            network="signet",
            oversight=oversight,
            signers=[wrong, str(keys[2].as_public()), str(keys[3].as_public())],
        )


def test_addresses_are_deterministic_and_unique(keys):
    policy = make_policy(keys)
    first, second = ClanWallet(policy), ClanWallet(policy)
    addresses = [first.address(index) for index in range(5)]
    assert addresses == [second.address(index) for index in range(5)]
    assert len(set(addresses)) == 5
    assert all(address.startswith("tb1p") for address in addresses)
    # A different roster gives a different wallet.
    assert ClanWallet(make_policy(keys[1:])).address(0) != addresses[0]


def test_oversight_and_majority_can_spend(keys):
    policy = make_policy(keys)
    wallet = ClanWallet(policy)
    fund(wallet, 100_000)
    recipients = [Recipient(DESTINATION, 40_000)]
    draft = wallet.build_payout(
        recipients, fee_rate_sat_vb=2, max_fee_sats=2_000, allow_unconfirmed=True
    )
    assert 0 < draft.fee_sats <= 2_000
    signed = [sign_normal_path(policy, keys[i], draft.psbt) for i in (0, 1, 3)]
    result = wallet.finalize(draft.psbt, signed, recipients, max_fee_sats=2_000)
    assert result.txid == draft.txid
    assert result.raw_hex


@pytest.mark.parametrize("holders", [(1, 2, 3), (0, 1), (0,)])
def test_signatories_alone_or_too_few_cannot_spend(keys, holders):
    policy = make_policy(keys)
    wallet = ClanWallet(policy)
    fund(wallet, 100_000)
    recipients = [Recipient(DESTINATION, 40_000)]
    draft = wallet.build_payout(
        recipients, fee_rate_sat_vb=2, max_fee_sats=2_000, allow_unconfirmed=True
    )
    signed = [sign_normal_path(policy, keys[i], draft.psbt) for i in holders]
    with pytest.raises(ClanWalletError, match="required signatures"):
        wallet.finalize(draft.psbt, signed, recipients, max_fee_sats=2_000)


def test_payout_checks_destination_amount_and_fee(keys):
    policy = make_policy(keys)
    wallet = ClanWallet(policy)
    fund(wallet, 100_000)
    recipients = [Recipient(DESTINATION, 40_000)]
    draft = wallet.build_payout(
        recipients, fee_rate_sat_vb=2, max_fee_sats=2_000, allow_unconfirmed=True
    )
    with pytest.raises(ClanWalletError, match="do not match"):
        wallet.check_payout(draft.psbt, [Recipient(OTHER_DESTINATION, 40_000)], max_fee_sats=2_000)
    with pytest.raises(ClanWalletError, match="do not match"):
        wallet.check_payout(draft.psbt, [Recipient(DESTINATION, 39_999)], max_fee_sats=2_000)
    with pytest.raises(ClanWalletError, match="fee"):
        wallet.check_payout(draft.psbt, recipients, max_fee_sats=draft.fee_sats - 1)
    with pytest.raises(ClanWalletError, match="fee"):
        wallet.build_payout(
            recipients, fee_rate_sat_vb=50, max_fee_sats=2_000, allow_unconfirmed=True
        )


def two_oversight_policy(keys):
    return ClanPolicy.create(
        network="signet",
        oversight=[str(keys[0].as_public()), str(keys[7].as_public())],
        signers=[str(key.as_public()) for key in keys[1:4]],
    )


def test_any_one_of_several_oversight_keys_can_approve(keys):
    policy = two_oversight_policy(keys)
    assert "and_v(v:multi_a(1," in policy.descriptor("external")
    recipients = [Recipient(DESTINATION, 40_000)]
    for afribit in (0, 7):
        wallet = ClanWallet(policy)
        fund(wallet, 100_000)
        draft = wallet.build_payout(
            recipients, fee_rate_sat_vb=2, max_fee_sats=2_000, allow_unconfirmed=True
        )
        signed = [sign_normal_path(policy, keys[i], draft.psbt) for i in (afribit, 1, 2)]
        assert wallet.finalize(draft.psbt, signed, recipients, max_fee_sats=2_000).raw_hex
    # Both Afribit keys together still need the clan majority.
    wallet = ClanWallet(policy)
    fund(wallet, 100_000)
    draft = wallet.build_payout(
        recipients, fee_rate_sat_vb=2, max_fee_sats=2_000, allow_unconfirmed=True
    )
    signed = [sign_normal_path(policy, keys[i], draft.psbt) for i in (0, 7, 1)]
    with pytest.raises(ClanWalletError, match="required signatures"):
        wallet.finalize(draft.psbt, signed, recipients, max_fee_sats=2_000)


def test_oversight_key_count_is_limited(keys):
    with pytest.raises(ClanWalletError, match="one to three"):
        ClanPolicy.create(
            network="signet",
            oversight=[str(key.as_public()) for key in (keys[0], keys[4], keys[5], keys[6])],
            signers=[str(key.as_public()) for key in keys[1:4]],
        )


def test_beneficiary_can_pay_the_network_fee(keys):
    policy = make_policy(keys)
    wallet = ClanWallet(policy)
    fund(wallet, 100_000)
    recipients = [Recipient(DESTINATION, 40_000)]
    draft = wallet.build_payout(
        recipients,
        fee_rate_sat_vb=2,
        max_fee_sats=2_000,
        fee_paid_by="recipients",
        allow_unconfirmed=True,
    )
    assert draft.received == [Recipient(DESTINATION, 40_000 - draft.fee_sats)]
    outputs = {
        str(bdk.Address.from_script(o.script_pubkey, bdk.Network.SIGNET)): o.value.to_sat()
        for o in bdk.Psbt(draft.psbt).extract_tx_unchecked_fee_rate().output()
    }
    assert outputs[DESTINATION] == 40_000 - draft.fee_sats
    # Change is what is left after the approved amount: the clan pays out exactly 40,000.
    assert sum(outputs.values()) + draft.fee_sats == 100_000
    assert sum(v for a, v in outputs.items() if a != DESTINATION) == 60_000
    # The full-amount version of the same payment does not match this rule.
    with pytest.raises(ClanWalletError, match="do not match"):
        wallet.check_payout(draft.psbt, recipients, max_fee_sats=2_000)
    signed = [sign_normal_path(policy, keys[i], draft.psbt) for i in (0, 1, 2)]
    result = wallet.finalize(
        draft.psbt, signed, recipients, max_fee_sats=2_000, fee_paid_by="recipients"
    )
    assert result.fee_sats == draft.fee_sats


def test_fee_is_shared_between_beneficiaries_in_a_batch(keys):
    wallet = ClanWallet(make_policy(keys))
    fund(wallet, 100_000)
    recipients = [Recipient(DESTINATION, 30_000), Recipient(OTHER_DESTINATION, 20_000)]
    draft = wallet.build_payout(
        recipients,
        fee_rate_sat_vb=3,
        max_fee_sats=3_000,
        fee_paid_by="recipients",
        allow_unconfirmed=True,
    )
    first, second = fee_shares(draft.fee_sats, 2)
    assert first + second == draft.fee_sats and 0 <= first - second <= 1
    assert draft.received == [
        Recipient(DESTINATION, 30_000 - first),
        Recipient(OTHER_DESTINATION, 20_000 - second),
    ]


def test_fee_cannot_swallow_a_small_grant():
    with pytest.raises(ClanWalletError, match="too little"):
        amounts_received([Recipient(DESTINATION, 1_400)], 500, "recipients")
    with pytest.raises(ClanWalletError, match="fee payer"):
        amounts_received([Recipient(DESTINATION, 40_000)], 500, "someone")
    assert amounts_received([Recipient(DESTINATION, 40_000)], 500, "clan") == [
        Recipient(DESTINATION, 40_000)
    ]


def test_signatures_for_another_payment_are_rejected(keys):
    policy = make_policy(keys)
    wallet = ClanWallet(policy)
    fund(wallet, 100_000)
    first = wallet.build_payout(
        [Recipient(DESTINATION, 40_000)],
        fee_rate_sat_vb=2,
        max_fee_sats=2_000,
        allow_unconfirmed=True,
    )
    other = wallet.build_payout(
        [Recipient(DESTINATION, 30_000)],
        fee_rate_sat_vb=2,
        max_fee_sats=2_000,
        allow_unconfirmed=True,
    )
    signed = [sign_normal_path(policy, keys[i], other.psbt) for i in (0, 1, 2)]
    with pytest.raises(ClanWalletError, match="different payment"):
        wallet.finalize(first.psbt, signed, [Recipient(DESTINATION, 40_000)], max_fee_sats=2_000)


def test_unconfirmed_deposits_are_not_spent_by_default(keys):
    wallet = ClanWallet(make_policy(keys))
    fund(wallet, 100_000)
    assert wallet.balance_sats() == 100_000
    assert wallet.confirmed_sats() == 0
    with pytest.raises(ClanWalletError, match="confirmed funds"):
        wallet.build_payout([Recipient(DESTINATION, 40_000)], fee_rate_sat_vb=2, max_fee_sats=2_000)


def test_invalid_payment_data_is_rejected(keys):
    wallet = ClanWallet(make_policy(keys))
    with pytest.raises(ClanWalletError, match="PSBT"):
        wallet.check_payout("not-a-psbt", [Recipient(DESTINATION, 1)], max_fee_sats=1)
    with pytest.raises(ClanWalletError, match="destination"):
        wallet.build_payout([Recipient("bc1qinvalid", 1)], fee_rate_sat_vb=1, max_fee_sats=1)
