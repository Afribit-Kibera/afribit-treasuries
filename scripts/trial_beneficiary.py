"""The grant beneficiary's own Bitcoin wallet for the mainnet trial: a plain single-key wallet.

It plays the part of the member's phone wallet (Phoenix, Blue Wallet and so on): it receives
the grant payout and sends the repayment. Its 12 words are kept in the trial folder.
"""

from pathlib import Path

import bdkpython as bdk

NETWORK = bdk.Network.BITCOIN


class BeneficiaryWallet:
    def __init__(self, words_file: Path, esplora: str):
        if not words_file.exists():
            words_file.parent.mkdir(parents=True, exist_ok=True)
            words_file.write_text(str(bdk.Mnemonic(bdk.WordCount.WORDS12)) + "\n", "utf-8")
        mnemonic = bdk.Mnemonic.from_string(words_file.read_text("utf-8").strip())
        key = bdk.DescriptorSecretKey(bdk.NetworkKind.MAIN, mnemonic, None)
        self.wallet = bdk.Wallet(
            bdk.Descriptor.new_bip84(key, bdk.KeychainKind.EXTERNAL, bdk.NetworkKind.MAIN),
            bdk.Descriptor.new_bip84(key, bdk.KeychainKind.INTERNAL, bdk.NetworkKind.MAIN),
            NETWORK,
            bdk.Persister.new_in_memory(),
        )
        self.client = bdk.EsploraClient(esplora)

    def address(self, index: int = 0) -> str:
        return str(self.wallet.peek_address(bdk.KeychainKind.EXTERNAL, index).address)

    def sync(self) -> int:
        request = self.wallet.start_full_scan().build()
        self.wallet.apply_update(self.client.full_scan(request, 10, 2))
        return self.balance()

    def balance(self) -> int:
        return self.wallet.balance().total.to_sat()

    def confirmed(self) -> int:
        return self.wallet.balance().confirmed.to_sat()

    def send(self, address: str, amount_sats: int | None, fee_rate: int = 1) -> str:
        """Pay an address. With no amount, send everything (the wallet pays the fee)."""
        script = bdk.Address(address, NETWORK).script_pubkey()
        builder = bdk.TxBuilder().fee_rate(bdk.FeeRate.from_sat_per_vb(fee_rate))
        if amount_sats is None:
            builder = builder.drain_wallet().drain_to(script)
        else:
            builder = builder.add_recipient(script, bdk.Amount.from_sat(amount_sats))
        psbt = builder.finish(self.wallet)
        assert self.wallet.sign(psbt), "The beneficiary wallet couldn't sign"
        tx = psbt.extract_tx()
        self.client.broadcast(tx)
        return str(tx.compute_txid())
