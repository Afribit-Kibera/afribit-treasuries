"""Shared test-only helpers for clan wallet tests. Real keys are created on phones."""

import struct

import bdkpython as bdk

from clans.clan_wallet import ACCOUNT_PATH, BRANCHES, ClanPolicy, ClanWallet

DESTINATION = "tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx"
OTHER_DESTINATION = "tb1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3q0sl5k7"


def secret_key(seed: int) -> bdk.DescriptorSecretKey:
    """Deterministic test-only keys. Real signatory keys are created on their phones."""
    mnemonic = bdk.Mnemonic.from_entropy(bytes([seed]) * 16)
    master = bdk.DescriptorSecretKey(bdk.NetworkKind.TEST, mnemonic, None)
    return master.derive(bdk.DerivationPath("m/" + ACCOUNT_PATH))


def make_policy(keys, signers=3, **options):
    return ClanPolicy.create(
        network="signet",
        oversight=str(keys[0].as_public()),
        signers=[str(key.as_public()) for key in keys[1 : signers + 1]],
        **options,
    )


def fund(wallet: ClanWallet, amount_sats: int, index: int = 0) -> None:
    """Load a made-up deposit into the watch-only wallet without touching any network."""
    wallet.reveal_to(index)
    script = bytes(
        bdk.Address(wallet.address(index), bdk.Network.SIGNET).script_pubkey().to_bytes()
    )
    raw = (
        struct.pack("<I", 2)
        + b"\x01"
        + bytes([index + 1]) * 32
        + struct.pack("<I", 0)
        + b"\x00"
        + b"\xff\xff\xff\xff"
        + b"\x01"
        + struct.pack("<Q", amount_sats)
        + bytes([len(script)])
        + script
        + struct.pack("<I", 0)
    )
    tx = bdk.Transaction(raw)
    wallet.wallet.apply_unconfirmed_txs([bdk.UnconfirmedTx(tx=tx, last_seen=1)])


def sign_normal_path(policy: ClanPolicy, key: bdk.DescriptorSecretKey, psbt: str) -> str:
    """Sign as one key holder, only on the normal spending path."""
    public = str(key.as_public())

    def private(keychain):
        normal, _ = BRANCHES[keychain]
        text = policy.descriptor(keychain)
        target = f"{public}/{normal}/*"
        assert text.count(target) == 1
        return bdk.Descriptor(text.replace(target, f"{key}/{normal}/*"), bdk.NetworkKind.TEST)

    signer = bdk.Wallet(
        private("external"), private("internal"), bdk.Network.SIGNET, bdk.Persister.new_in_memory()
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
