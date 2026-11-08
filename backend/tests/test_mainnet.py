"""Bitcoin mainnet wallets: xpub keys at 87'/0'/0', bc1p addresses, and an explicit switch."""

import json
import struct

import bdkpython as bdk
import pytest
from clan_wallet_helpers import DESTINATION as TEST_DESTINATION
from pydantic import ValidationError
from test_clan_wallet_api import make_app, phone_code, three_signer_clan
from test_clan_wallet_payments import FakeChain, accepted_grant, fund_clan

from clans import oversight, recover
from clans.chain_watcher import ChainWatcher
from clans.clan_wallet import BRANCHES, ClanPolicy, ClanWallet, ClanWalletError, Recipient
from clans.live_config import LiveSettings

PASSPHRASE = "correct horse battery staple"
WORDS = str(bdk.Mnemonic.from_entropy(bytes([9]) * 16))
DESTINATION = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"


def words(seed: int) -> str:
    return str(bdk.Mnemonic.from_entropy(bytes([seed]) * 16))


def main_key(seed: int) -> bdk.DescriptorSecretKey:
    return recover.account_key(words(seed), "bitcoin")


def test_test_network_keys_are_unchanged():
    # The same words still give the same test key, so existing wallets are untouched.
    assert str(recover.account_key(words(1)).as_public()).startswith("[")
    assert "/87'/1'/0']tpub" in str(recover.account_key(words(1)).as_public())
    assert "/87'/0'/0']xpub" in str(main_key(1).as_public())


def mainnet_policy(oversight_key: str | None = None) -> ClanPolicy:
    return ClanPolicy.create(
        network="bitcoin",
        oversight=oversight_key or str(main_key(4).as_public()),
        signers=[str(main_key(seed).as_public()) for seed in (1, 2, 3)],
    )


def test_mainnet_wallet_has_mainnet_addresses_and_unspendable_key():
    policy = mainnet_policy()
    assert policy.unspendable_key().startswith("xpub")
    wallet = ClanWallet(policy)
    assert wallet.address(0).startswith("bc1p")
    assert len(policy.wallet_code()) == 8


def test_keys_must_match_the_network():
    test_keys = [str(recover.account_key(words(seed)).as_public()) for seed in (1, 2, 3, 4)]
    with pytest.raises(ClanWalletError, match="network"):
        ClanPolicy.create(network="bitcoin", oversight=test_keys[0], signers=test_keys[1:])
    main_keys = [str(main_key(seed).as_public()) for seed in (1, 2, 3, 4)]
    with pytest.raises(ClanWalletError, match="network"):
        ClanPolicy.create(network="signet", oversight=main_keys[0], signers=main_keys[1:])
    # An xpub must come from the mainnet account path.
    wrong = main_keys[0].replace("87'/0'/0'", "87'/1'/0'")
    with pytest.raises(ClanWalletError, match="account path"):
        ClanPolicy.create(network="bitcoin", oversight=wrong, signers=main_keys[1:])


def test_mainnet_is_the_default_network(monkeypatch):
    for name, value in {
        "DATABASE_URL": "sqlite://",
        "ENVIRONMENT": "test",
        "SESSION_SECRET": "a" * 64,
        "PUBLIC_ORIGIN": "http://localhost:8000",
        "RP_ID": "localhost",
    }.items():
        monkeypatch.setenv("CLANS_" + name, value)
    monkeypatch.setenv("CLANS_CLAN_WALLETS_ENABLED", "true")
    monkeypatch.setenv("CLANS_CLAN_WALLET_OVERSIGHT_KEYS", str(main_key(4).as_public()))
    settings = LiveSettings()
    assert settings.clan_wallet_network == "bitcoin"
    assert settings.esplora_urls == ["https://mempool.space/api", "https://blockstream.info/api"]
    monkeypatch.setenv(
        "CLANS_CLAN_WALLET_OVERSIGHT_KEYS", str(recover.account_key(words(4)).as_public())
    )
    with pytest.raises(ValidationError, match="made for the wallet network"):
        LiveSettings()
    # A test network is a deliberate choice, and its keys are tpub keys.
    monkeypatch.setenv("CLANS_CLAN_WALLET_NETWORK", "signet")
    assert LiveSettings().clan_wallet_network == "signet"


def fund(wallet: ClanWallet, amount_sats: int) -> None:
    script = bytes(bdk.Address(wallet.address(0), bdk.Network.BITCOIN).script_pubkey().to_bytes())
    raw = (
        struct.pack("<I", 2)
        + b"\x01"
        + bytes([7]) * 32
        + struct.pack("<I", 0)
        + b"\x00\xff\xff\xff\xff\x01"
        + struct.pack("<Q", amount_sats)
        + bytes([len(script)])
        + script
        + struct.pack("<I", 0)
    )
    wallet.wallet.apply_unconfirmed_txs([bdk.UnconfirmedTx(tx=bdk.Transaction(raw), last_seen=1)])


def sign_as(policy: ClanPolicy, key: bdk.DescriptorSecretKey, psbt: str) -> str:
    public = str(key.as_public())

    def private(keychain):
        normal, _ = BRANCHES[keychain]
        text = policy.descriptor(keychain).replace(f"{public}/{normal}/*", f"{key}/{normal}/*")
        return bdk.Descriptor(text, bdk.NetworkKind.MAIN)

    signer = bdk.Wallet(
        private("external"), private("internal"), bdk.Network.BITCOIN, bdk.Persister.new_in_memory()
    )
    copy = bdk.Psbt(psbt)
    signer.sign(
        copy,
        bdk.SignOptions(
            trust_witness_utxo=False,
            assume_height=None,
            allow_all_sighashes=False,
            try_finalize=False,
            sign_with_tap_internal_key=False,
            allow_grinding=True,
        ),
    )
    return copy.serialize()


def test_oversight_laptop_signs_a_mainnet_payout(tmp_path):
    words_out, test_public = oversight.create_key(tmp_path, PASSPHRASE, WORDS)
    assert test_public == oversight.public_key(tmp_path)
    main_public = oversight.public_key(tmp_path, "bitcoin")
    assert "/87'/0'/0']xpub" in main_public
    policy = mainnet_policy(main_public)
    view = {
        "generation": 1,
        "policy": {
            "network": "bitcoin",
            "oversight": [main_public],
            "signers": [str(key) for key in policy.signers],
            "recovery_threshold": policy.recovery_threshold,
            "recovery_blocks": policy.recovery_blocks,
        },
    }
    oversight.add_wallet(tmp_path, "clan-1", view, policy.wallet_code())
    assert oversight.clan_address(tmp_path, "clan-1").startswith("bc1p")
    start, end = oversight.check_characters(DESTINATION)
    oversight.confirm_address(tmp_path, DESTINATION, "Amina", start, end, "bitcoin")

    wallet = ClanWallet(policy)
    fund(wallet, 200_000)
    recipients = [Recipient(DESTINATION, 40_000)]
    draft = wallet.build_payout(
        recipients,
        fee_rate_sat_vb=2,
        max_fee_sats=3_000,
        allow_unconfirmed=True,
        fee_paid_by="recipients",
    )
    combined = bdk.Psbt(draft.psbt)
    for seed in (1, 2):
        combined = combined.combine(bdk.Psbt(sign_as(policy, main_key(seed), draft.psbt)))
    request = {
        "clan_id": "clan-1",
        "psbt": combined.serialize(),
        "fee_paid_by": "recipients",
        "max_fee_sats": 3_000,
        "recipients": [
            {"grant_id": "g1", "name": "Amina", "address": DESTINATION, "approved_sats": 40_000}
        ],
    }
    signed, complete = oversight.sign(tmp_path, request, PASSPHRASE)
    assert complete
    done = wallet.finalize(
        request["psbt"], [signed], recipients, max_fee_sats=3_000, fee_paid_by="recipients"
    )
    assert done.raw_hex


def test_older_laptop_keys_gain_a_mainnet_key_on_unlock(tmp_path):
    oversight.create_key(tmp_path, PASSPHRASE, WORDS)
    path = tmp_path / oversight.KEY_FILE
    record = json.loads(path.read_text())
    expected = record.pop("mainnet_public_key")
    path.write_text(json.dumps(record))
    with pytest.raises(oversight.OversightError, match="before mainnet"):
        oversight.public_key(tmp_path, "bitcoin")
    with pytest.raises(oversight.OversightError, match="Wrong passphrase"):
        oversight.unlock(tmp_path, "not the passphrase at all")
    oversight.unlock(tmp_path, PASSPHRASE)
    assert oversight.public_key(tmp_path, "bitcoin") == expected


def test_mainnet_grants_are_paid_to_mainnet_addresses(tmp_path):
    keys = [str(main_key(seed).as_public()) for seed in (4, 1, 2, 3)]
    app = make_app(tmp_path, keys, clan_wallet_network="bitcoin")
    cid, signers, member = three_signer_clan(app)
    route = f"/api/clans/{cid}/wallet"
    for client, key in zip(signers, keys[1:], strict=True):
        assert client.post(route + "/keys", json={"key": key}).status_code == 200
    view = signers[0].get(route).json()
    for client in signers:
        assert client.post(route + "/confirm", json={"wallet_code": phone_code(view)}).is_success
    chain = FakeChain(bdk.Network.BITCOIN)
    watcher = ChainWatcher(app.state.security.settings, chain=chain)
    clan = {"app": app, "cid": cid, "signers": signers, "chain": chain, "watcher": watcher}
    try:
        fund_clan(clan, 100_000)
        grant = accepted_grant(clan)
        address = f"/api/clans/{cid}/grants/{grant}/payout-address"
        refused = signers[0].post(address, json={"address": TEST_DESTINATION})
        assert refused.status_code == 400
        assert "starts with bc1q or bc1p" in refused.json()["detail"]
        paid = signers[0].post(address, json={"address": DESTINATION})
        assert paid.status_code == 200, paid.text
    finally:
        watcher.security.engine.dispose()
        app.state.security.engine.dispose()


def test_the_chain_watcher_backs_off_when_the_explorer_refuses():
    from clans.chain_watcher import INTERVAL_SECONDS, MAX_BACKOFF_SECONDS, next_delay

    assert next_delay(0) == INTERVAL_SECONDS
    assert next_delay(1) == 2 * INTERVAL_SECONDS
    assert next_delay(3) == 8 * INTERVAL_SECONDS
    assert next_delay(50) == MAX_BACKOFF_SECONDS
