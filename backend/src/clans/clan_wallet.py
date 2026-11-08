"""Per-clan Bitcoin multisig wallets. Clans stores public keys only and can never spend.

Each clan wallet is a Taproot output with two script paths and no usable key path:

* Normal spending: one Afribit oversight key AND a majority of the clan's signatories.
  Afribit may hold up to three oversight keys (for example one Ledger per staff member);
  any one of them is enough, so one person being away never blocks payouts.
* Recovery: after a period with no spending, a set number of signatories alone.

Oversight keys live on separate signing devices. A compromised Clans server or frontend
can collect signatory signatures, but cannot reach an oversight key, so it cannot move
funds. Afribit alone can never spend, and the recovery path stops Afribit from freezing
a clan's money.

Test networks (signet, testnet4) use `87'/1'/0'` tpub keys. Bitcoin mainnet uses
`87'/0'/0'` xpub keys. Mainnet is the server's default network. A wallet's keys must all
belong to its network.
"""

import base64
import hashlib
import math
import re
from dataclasses import dataclass

import bdkpython as bdk

# BIP-341 "nothing up my sleeve" point: nobody knows its private key, so the key path
# is unspendable and every spend must use one of the two scripts. Each wallet uses it
# as an extended key with its own chain code (the approach Liana uses). That keeps clan
# wallets from sharing a visible marker, and lets hardware signers such as Ledger,
# which need every key in extended form, register the wallet.
UNSPENDABLE_KEY = "50929b74c1a04954b78b4b6035e97a5e078a5a0f28ec96d547bfee9ace803ac0"
UNSPENDABLE_TAG = b"Afribit Clans unspendable key v1"
TPUB_VERSION = bytes.fromhex("043587cf")
XPUB_VERSION = bytes.fromhex("0488b21e")
BASE58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

NETWORKS = {
    "signet": bdk.Network.SIGNET,
    "testnet4": bdk.Network.TESTNET4,
    "bitcoin": bdk.Network.BITCOIN,
}
MAINNET = "bitcoin"
# BIP-87 multisig account paths. Coin type 1 is shared by all test networks.
ACCOUNT_PATH = "87'/1'/0'"
MAINNET_ACCOUNT_PATH = "87'/0'/0'"
MAJORITY = {3: 2, 5: 3, 7: 4}
MAX_OVERSIGHT_KEYS = 3
# Roughly six months of blocks. Bitcoin's relative timelock cannot exceed 65,535 blocks.
DEFAULT_RECOVERY_BLOCKS = 26_280
MIN_RECOVERY_BLOCKS = 4_320
MAX_RECOVERY_BLOCKS = 65_535
# Smallest amount a beneficiary may receive after paying the network fee.
MIN_PAYOUT_SATS = 1_000
# Change addresses are checked up to this index. A clan makes far fewer payouts than this.
# Change, refresh and move payments use only the first 1,000 change addresses, and
# recovery checks all of them. A server can't hide money at an address nobody scans.
MAX_CHANGE_INDEX = 1_000
FEE_PAYERS = {"clan", "recipients"}

# Derivation branches. Recovery keys use separate branches so the same signatory key
# never repeats inside one wallet output (the approach Liana uses).
BRANCHES = {"external": (0, 2), "internal": (1, 3)}
KEYCHAINS = {"external": bdk.KeychainKind.EXTERNAL, "internal": bdk.KeychainKind.INTERNAL}
# Normal spending is the second item in BDK's policy tree: the unspendable key is first.
NORMAL_PATH = [1]
RECOVERY_PATH = [2]

KEY_PATTERN = re.compile(
    r"^\[([0-9a-f]{8})/([0-9h']+(?:/[0-9h']+)*)\]([tx]pub[1-9A-HJ-NP-Za-km-z]+)$"
)


def account_path(network: str) -> str:
    return MAINNET_ACCOUNT_PATH if network == MAINNET else ACCOUNT_PATH


def network_kind(network: str):
    return bdk.NetworkKind.MAIN if network == MAINNET else bdk.NetworkKind.TEST


class ClanWalletError(ValueError):
    """The wallet setup or a payment does not match the clan's agreed rules."""


class SignatureError(ClanWalletError):
    """A payment could not be completed. `bad_keys` lists x-only keys whose signature failed."""

    def __init__(self, message: str, bad_keys: tuple[str, ...] = ()):
        super().__init__(message)
        self.bad_keys = bad_keys


BAD_SIGNATURE = re.compile(r"bad schnorr signature with pk ([0-9a-f]{64})")
# Measured sizes of a one-input, one-payee payout (see the plan's fee table), and what each
# extra coin spent adds. Each extra oversight key adds about 9 vB. Used only for fee
# estimates shown before a payout exists.
PAYOUT_VBYTES = {3: 226, 5: 260, 7: 294}
PAYOUT_INPUT_VBYTES = {3: 142, 5: 175, 7: 209}
EXTRA_OVERSIGHT_VBYTES = 9
# BDK counts fee rates in sats per 1,000 weight units: 1 sat/vB is 250.
SAT_KWU_PER_SAT_VB = 250


def fee_rate_kwu(sat_vb: float) -> int:
    """A fee rate in sat/vB, which may have decimals, in BDK's unit, never below it."""
    return math.ceil(round(sat_vb * SAT_KWU_PER_SAT_VB, 6))


def bdk_fee_rate(sat_vb: float) -> bdk.FeeRate:
    return bdk.FeeRate.from_sat_per_kwu(fee_rate_kwu(sat_vb))


@dataclass(frozen=True)
class SignerKey:
    """An account-level public key with its origin, as `[fingerprint/87'/1'/0']tpub...`.

    Mainnet keys are `[fingerprint/87'/0'/0']xpub...`.
    """

    fingerprint: str
    path: str
    xpub: str

    @classmethod
    def parse(cls, value: str) -> "SignerKey":
        match = KEY_PATTERN.match(value.strip())
        if not match:
            raise ClanWalletError("Expected a public key with its origin")
        fingerprint, path, xpub = match.groups()
        path = path.replace("h", "'")
        expected = MAINNET_ACCOUNT_PATH if xpub.startswith("xpub") else ACCOUNT_PATH
        if path != expected:
            raise ClanWalletError("Signer keys must use the clan account path " + expected)
        try:
            parsed = bdk.DescriptorPublicKey.from_string(f"[{fingerprint}/{path}]{xpub}")
        except Exception as exc:
            raise ClanWalletError("The public key is not valid") from exc
        if parsed.is_multipath():
            raise ClanWalletError("Signer keys must be single account keys")
        return cls(fingerprint, path, xpub)

    @property
    def mainnet(self) -> bool:
        return self.xpub.startswith("xpub")

    def __str__(self) -> str:
        return f"[{self.fingerprint}/{self.path}]{self.xpub}"


@dataclass(frozen=True)
class ClanPolicy:
    network: str
    # Afribit's oversight keys, in the configured order. Any one of them can approve.
    oversight: tuple[SignerKey, ...]
    signers: tuple[SignerKey, ...]
    recovery_threshold: int
    recovery_blocks: int = DEFAULT_RECOVERY_BLOCKS

    @classmethod
    def create(
        cls,
        *,
        network: str,
        oversight: str | list[str],
        signers: list[str],
        recovery_threshold: int | None = None,
        recovery_blocks: int = DEFAULT_RECOVERY_BLOCKS,
    ) -> "ClanPolicy":
        keys = tuple(SignerKey.parse(value) for value in signers)
        approvers = [oversight] if isinstance(oversight, str) else oversight
        policy = cls(
            network=network,
            oversight=tuple(SignerKey.parse(value) for value in approvers),
            signers=keys,
            recovery_threshold=recovery_threshold or MAJORITY.get(len(keys), 0),
            recovery_blocks=recovery_blocks,
        )
        policy.validate()
        return policy

    @property
    def threshold(self) -> int:
        return MAJORITY[len(self.signers)]

    def validate(self):
        if self.network not in NETWORKS:
            raise ClanWalletError("Clan wallets use signet, testnet4 or Bitcoin mainnet")
        if any(key.mainnet != (self.network == MAINNET) for key in self.keys):
            raise ClanWalletError(
                "Every key must be made for this wallet's network (xpub for mainnet, "
                "tpub for test networks)"
            )
        if len(self.signers) not in MAJORITY:
            raise ClanWalletError("A clan needs 3, 5 or 7 signatories")
        if not 1 <= len(self.oversight) <= MAX_OVERSIGHT_KEYS:
            raise ClanWalletError("A clan wallet needs one to three Afribit oversight keys")
        everyone = (*self.oversight, *self.signers)
        if len({key.xpub for key in everyone}) != len(everyone):
            raise ClanWalletError("Every signatory and the oversight key must be different")
        if len({key.fingerprint for key in everyone}) != len(everyone):
            raise ClanWalletError("Every key must come from a different recovery phrase")
        if not self.threshold <= self.recovery_threshold <= len(self.signers):
            raise ClanWalletError("Recovery needs at least the normal signatory majority")
        if not MIN_RECOVERY_BLOCKS <= self.recovery_blocks <= MAX_RECOVERY_BLOCKS:
            raise ClanWalletError("The recovery wait must be between about 30 days and 15 months")

    @property
    def keys(self) -> tuple[SignerKey, ...]:
        return (*self.oversight, *self.signers)

    def unspendable_key(self) -> str:
        """The wallet's unspendable internal key: the BIP-341 point with a per-wallet chain code."""
        roster = "\n".join(str(key) for key in (*self.oversight, *self.signers))
        chain_code = hashlib.sha256(UNSPENDABLE_TAG + roster.encode()).digest()
        version = XPUB_VERSION if self.network == MAINNET else TPUB_VERSION
        payload = version + bytes(9) + chain_code + bytes.fromhex("02" + UNSPENDABLE_KEY)
        return _base58check(payload)

    def descriptor(self, keychain: str) -> str:
        """The public descriptor, without checksum. The frontend builds the same string."""
        normal, recovery = BRANCHES[keychain]
        signers = ",".join(f"{key}/{normal}/*" for key in self.signers)
        recovering = ",".join(f"{key}/{recovery}/*" for key in self.signers)
        if len(self.oversight) == 1:
            approval = f"v:pk({self.oversight[0]}/{normal}/*)"
        else:
            approvers = ",".join(f"{key}/{normal}/*" for key in self.oversight)
            approval = f"v:multi_a(1,{approvers})"
        return (
            f"tr({self.unspendable_key()}/{normal}/*,{{"
            f"and_v({approval},multi_a({self.threshold},{signers})),"
            f"and_v(v:multi_a({self.recovery_threshold},{recovering}),"
            f"older({self.recovery_blocks}))}})"
        )

    def bdk_descriptor(self, keychain: str) -> bdk.Descriptor:
        return bdk.Descriptor(self.descriptor(keychain), network_kind(self.network))

    def wallet_code(self) -> str:
        """A short code every signatory compares to confirm they joined the same wallet."""
        return str(self.bdk_descriptor("external")).rsplit("#", 1)[1]

    def estimated_payout_vbytes(self, coins: int = 1) -> int:
        """A guide to the size of a one-payee payout spending `coins` coins, for quotes."""
        count = len(self.signers)
        return (
            PAYOUT_VBYTES[count]
            + PAYOUT_INPUT_VBYTES[count] * (max(coins, 1) - 1)
            + EXTRA_OVERSIGHT_VBYTES * (len(self.oversight) - 1)
        )


@dataclass(frozen=True)
class Recipient:
    address: str
    amount_sats: int


def fee_shares(fee_sats: int, count: int) -> list[int]:
    """Split a fee evenly, giving any remainder to the first recipients in approved order."""
    base, extra = divmod(fee_sats, count)
    return [base + (1 if i < extra else 0) for i in range(count)]


def amounts_received(
    recipients: list[Recipient], fee_sats: int, fee_paid_by: str
) -> list[Recipient]:
    """What each recipient actually receives once the agreed party pays the network fee."""
    if fee_paid_by not in FEE_PAYERS:
        raise ClanWalletError("Unknown fee payer")
    if fee_paid_by == "clan":
        return list(recipients)
    shares = fee_shares(fee_sats, len(recipients))
    received = [
        Recipient(r.address, r.amount_sats - share)
        for r, share in zip(recipients, shares, strict=True)
    ]
    if any(r.amount_sats < MIN_PAYOUT_SATS for r in received):
        raise ClanWalletError("The network fee would leave a beneficiary with too little")
    return received


@dataclass(frozen=True)
class PayoutDraft:
    psbt: str
    txid: str
    fee_sats: int
    # Approved amounts. With fee_paid_by="recipients" each output is smaller by its fee share.
    recipients: tuple[Recipient, ...]
    fee_paid_by: str = "clan"

    @property
    def received(self) -> list[Recipient]:
        return amounts_received(list(self.recipients), self.fee_sats, self.fee_paid_by)


@dataclass(frozen=True)
class SweepDraft:
    """A refresh or a move: every chosen coin, minus the fee, to one clan change address."""

    psbt: str
    txid: str
    fee_sats: int
    amount_sats: int


@dataclass(frozen=True)
class SignedPayout:
    txid: str
    raw_hex: str
    fee_sats: int


class ClanWallet:
    """A watch-only view of one clan wallet. It can build payments but holds no keys."""

    def __init__(self, policy: ClanPolicy, persister=None):
        policy.validate()
        self.policy = policy
        self.network = NETWORKS[policy.network]
        self.wallet = bdk.Wallet(
            policy.bdk_descriptor("external"),
            policy.bdk_descriptor("internal"),
            self.network,
            persister or bdk.Persister.new_in_memory(),
        )

    def address(self, index: int) -> str:
        """The receiving address at a fixed index, for example one per grant repayment."""
        if index < 0 or index >= 2**31:
            raise ClanWalletError("Invalid address index")
        return str(self.wallet.peek_address(bdk.KeychainKind.EXTERNAL, index).address)

    def change_address(self, index: int) -> str:
        """The change address at a fixed index. Refreshes and moves pay one of these."""
        if index < 0 or index >= MAX_CHANGE_INDEX:
            raise ClanWalletError("Invalid change address index")
        return str(self.wallet.peek_address(bdk.KeychainKind.INTERNAL, index).address)

    def reveal_to(self, index: int):
        """Make sure addresses up to `index` are watched."""
        self.wallet.reveal_addresses_to(bdk.KeychainKind.EXTERNAL, index)

    def balance_sats(self) -> int:
        return self.wallet.balance().total.to_sat()

    def confirmed_sats(self) -> int:
        return self.wallet.balance().confirmed.to_sat()

    def sync(self, esplora_url: str, *, stop_gap: int = 25, all_change: bool = False):
        """Refresh from a block explorer. Read-only: no keys or spending ability involved.

        With all_change, every allowed change address is checked too, however many are unused.
        """
        client = bdk.EsploraClient(esplora_url)
        request = self.wallet.start_full_scan().build()
        self.wallet.apply_update(client.full_scan(request, stop_gap, 4))
        if all_change:
            self.wallet.reveal_addresses_to(bdk.KeychainKind.INTERNAL, MAX_CHANGE_INDEX - 1)
            request = self.wallet.start_sync_with_revealed_spks().build()
            self.wallet.apply_update(client.sync(request, 4))

    def _script(self, address: str) -> bdk.Script:
        try:
            parsed = bdk.Address(address, self.network)
        except Exception as exc:
            raise ClanWalletError("The destination address is not valid on this network") from exc
        return parsed.script_pubkey()

    def _build(
        self, recipients, fee_rate_sat_vb, allow_unconfirmed, utxos=None, change=None
    ) -> bdk.Psbt:
        # Largest coins first: fewest coins, and the same choice the fee preview assumes.
        builder = (
            bdk.TxBuilder()
            .fee_rate(bdk_fee_rate(fee_rate_sat_vb))
            .coin_selection(bdk.CoinSelectionAlgorithm.LARGEST_FIRST)
        )
        if change is not None:
            builder = builder.drain_to(change)
        for recipient in recipients:
            builder = builder.add_recipient(
                self._script(recipient.address), bdk.Amount.from_sat(recipient.amount_sats)
            )
        if utxos is not None:
            builder = builder.add_utxos(utxos).manually_selected_only()
        if not allow_unconfirmed:
            builder = builder.exclude_unconfirmed()
        for keychain in KEYCHAINS.values():
            policy_id = self.wallet.policies(keychain).id()
            builder = builder.policy_path({policy_id: NORMAL_PATH}, keychain)
        try:
            return builder.finish(self.wallet)
        except bdk.CreateTxError as exc:
            raise ClanWalletError("Not enough confirmed funds for this payout") from exc

    def build_payout(
        self,
        recipients: list[Recipient],
        *,
        fee_rate_sat_vb: float,
        max_fee_sats: int,
        fee_paid_by: str = "clan",
        allow_unconfirmed: bool = False,
        utxos: list[bdk.OutPoint] | None = None,
        change: bdk.Script | None = None,
    ) -> PayoutDraft:
        """Build an unsigned payment that can only be signed through the normal path.

        With fee_paid_by="recipients", each beneficiary receives the approved amount minus
        an equal share of the network fee, and the clan pays out exactly the approved total.
        `utxos` limits the payment to exactly those coins, for example so that a new version
        of a payout spends the same coins as the old one and only one can ever confirm.
        """
        if not recipients or any(r.amount_sats <= 0 for r in recipients):
            raise ClanWalletError("A payout needs at least one positive amount")
        if not 1 <= fee_rate_sat_vb <= 1_000:
            raise ClanWalletError("Unreasonable network fee rate")
        if fee_paid_by not in FEE_PAYERS:
            raise ClanWalletError("Unknown fee payer")
        psbt = self._build(recipients, fee_rate_sat_vb, allow_unconfirmed, utxos, change)
        if fee_paid_by == "recipients":
            # Keep the same coins and shrink the outputs by the fee until the fee settles.
            # Smaller outputs can only add change, so this settles in a step or two.
            utxos = [txin.previous_output for txin in psbt.extract_tx_unchecked_fee_rate().input()]
            fee = psbt.fee()
            for _ in range(4):
                received = amounts_received(recipients, fee, fee_paid_by)
                psbt = self._build(received, fee_rate_sat_vb, allow_unconfirmed, utxos, change)
                if psbt.fee() == fee:
                    break
                fee = psbt.fee()
            else:
                raise ClanWalletError("Could not settle the network fee for this payout")
        draft = PayoutDraft(
            psbt=psbt.serialize(),
            txid=str(psbt.extract_tx_unchecked_fee_rate().compute_txid()),
            fee_sats=psbt.fee(),
            recipients=tuple(recipients),
            fee_paid_by=fee_paid_by,
        )
        self.check_payout(
            draft.psbt, recipients, max_fee_sats=max_fee_sats, fee_paid_by=fee_paid_by
        )
        return draft

    def build_replacement(
        self,
        original_psbt: str,
        recipients: list[Recipient],
        *,
        fee_rate_sat_vb: float,
        max_fee_sats: int,
        fee_paid_by: str,
    ) -> PayoutDraft:
        """A higher-fee version of a payment already sent: the same coins and change address.

        This wallet sees those coins as spent by the payment on the network, so the new
        version is built in a separate view that knows only the transactions that created
        them. Because both versions spend the same coins, at most one can ever confirm.
        """
        original = _parse(original_psbt)
        view, coins = self._spent_view(original)
        change = None
        for output in original.extract_tx_unchecked_fee_rate().output():
            found = self.wallet.derivation_of_spk(output.script_pubkey)
            if found is not None and found.keychain == bdk.KeychainKind.INTERNAL:
                change = output.script_pubkey
        draft = view.build_payout(
            recipients,
            fee_rate_sat_vb=fee_rate_sat_vb,
            max_fee_sats=max_fee_sats,
            fee_paid_by=fee_paid_by,
            allow_unconfirmed=True,
            utxos=coins,
            change=change,
        )
        if draft.fee_sats <= original.fee():
            raise ClanWalletError("The new version must pay a higher network fee")
        return draft

    def _spent_view(self, original: bdk.Psbt) -> tuple["ClanWallet", list[bdk.OutPoint]]:
        """A separate view of this wallet in which the coins `original` spends are unspent."""
        coins = [item.previous_output for item in original.extract_tx_unchecked_fee_rate().input()]
        parents = {}
        for coin in coins:
            known = self.wallet.get_tx(coin.txid)
            if known is None:
                raise ClanWalletError("The coins of the sent payment aren't known to this wallet")
            parents[str(coin.txid)] = known.transaction
        view = ClanWallet(self.policy)
        for keychain in KEYCHAINS.values():
            index = self.wallet.derivation_index(keychain)
            if index is not None:
                view.wallet.reveal_addresses_to(keychain, index)
        view.wallet.apply_unconfirmed_txs(
            [bdk.UnconfirmedTx(tx=parent, last_seen=1) for parent in parents.values()]
        )
        return view, coins

    def build_sweep(
        self,
        coins: list[bdk.OutPoint],
        destination: str,
        *,
        fee_rate_sat_vb: float,
        max_fee_sats: int,
    ) -> SweepDraft:
        """Spend exactly `coins`, all of them, to one address on the normal path.

        Used to refresh the recovery wait (to this wallet's own change address) and to move
        an earlier wallet's coins into the clan's newest wallet. The clan pays the fee.
        """
        if not coins:
            raise ClanWalletError("There are no coins to move")
        if not 1 <= fee_rate_sat_vb <= 1_000:
            raise ClanWalletError("Unreasonable network fee rate")
        builder = (
            bdk.TxBuilder()
            .fee_rate(bdk_fee_rate(fee_rate_sat_vb))
            .add_utxos(coins)
            .manually_selected_only()
            .drain_to(self._script(destination))
        )
        for keychain in KEYCHAINS.values():
            policy_id = self.wallet.policies(keychain).id()
            builder = builder.policy_path({policy_id: NORMAL_PATH}, keychain)
        try:
            psbt = builder.finish(self.wallet)
        except bdk.CreateTxError as exc:
            raise ClanWalletError("These coins can't be moved") from exc
        draft = SweepDraft(
            psbt=psbt.serialize(),
            txid=str(psbt.extract_tx_unchecked_fee_rate().compute_txid()),
            fee_sats=psbt.fee(),
            amount_sats=self.check_sweep(psbt.serialize(), destination, max_fee_sats=max_fee_sats),
        )
        return draft

    def build_sweep_replacement(
        self, original_psbt: str, destination: str, *, fee_rate_sat_vb: float, max_fee_sats: int
    ) -> SweepDraft:
        """A higher-fee version of a sent refresh or move: the same coins and destination."""
        original = _parse(original_psbt)
        view, coins = self._spent_view(original)
        draft = view.build_sweep(
            coins, destination, fee_rate_sat_vb=fee_rate_sat_vb, max_fee_sats=max_fee_sats
        )
        if draft.fee_sats <= original.fee():
            raise ClanWalletError("The new version must pay a higher network fee")
        return draft

    def check_sweep(self, psbt_base64: str, destination: str, *, max_fee_sats: int) -> int:
        """A refresh or move has one output, to the agreed address. Returns the amount moved.

        Callers work out `destination` from a clan wallet they checked themselves.
        """
        psbt = _parse(psbt_base64)
        if psbt.fee() > max_fee_sats:
            raise ClanWalletError("The network fee is above the approved limit")
        outputs = psbt.extract_tx_unchecked_fee_rate().output()
        target = bytes(self._script(destination).to_bytes())
        if len(outputs) != 1 or bytes(outputs[0].script_pubkey.to_bytes()) != target:
            raise ClanWalletError("The payment must move everything to the clan's own address")
        return outputs[0].value.to_sat()

    def check_payout(
        self,
        psbt_base64: str,
        recipients: list[Recipient],
        *,
        max_fee_sats: int,
        fee_paid_by: str = "clan",
    ):
        """Outputs must be exactly the approved recipients plus change back to this wallet."""
        psbt = _parse(psbt_base64)
        if psbt.fee() > max_fee_sats:
            raise ClanWalletError("The network fee is above the approved limit")
        received = amounts_received(list(recipients), psbt.fee(), fee_paid_by)
        expected = sorted(
            (bytes(self._script(r.address).to_bytes()), r.amount_sats) for r in received
        )
        paid = []
        details = psbt.output()
        for position, output in enumerate(psbt.extract_tx_unchecked_fee_rate().output()):
            script = output.script_pubkey
            if self._is_change(script, details[position]):
                continue
            if self.wallet.is_mine(script):
                raise ClanWalletError("Change must return to the clan's change addresses")
            paid.append((bytes(script.to_bytes()), output.value.to_sat()))
        if sorted(paid) != expected:
            raise ClanWalletError("The payment outputs do not match the approved payout")

    def _is_change(self, script: bdk.Script, detail) -> bool:
        """True when the output is one of this wallet's change addresses, at any index.

        A fresh watch-only wallet only knows the first few addresses. Later change addresses
        are found from the index the PSBT claims, then re-derived here, so a false claim fails.
        """
        derivation = self.wallet.derivation_of_spk(script)
        if derivation is not None:
            return derivation.keychain == bdk.KeychainKind.INTERNAL
        normal, _ = BRANCHES["internal"]
        target = bytes(script.to_bytes())
        claimed = set()
        for origin in detail.tap_key_origins.values():
            steps = str(origin.key_source.path).removeprefix("m/").split("/")
            if len(steps) >= 2 and steps[-2] == str(normal) and steps[-1].isdigit():
                claimed.add(int(steps[-1]))
        for index in sorted(claimed)[:4]:
            if index < MAX_CHANGE_INDEX:
                address = self.wallet.peek_address(bdk.KeychainKind.INTERNAL, index).address
                if bytes(address.script_pubkey().to_bytes()) == target:
                    return True
        return False

    def finalize(
        self,
        unsigned: str,
        signed: list[str],
        recipients: list[Recipient],
        *,
        max_fee_sats: int,
        fee_paid_by: str = "clan",
    ) -> SignedPayout:
        """Combine independently signed copies and produce the transaction to broadcast."""
        return self._finish(
            unsigned,
            signed,
            lambda psbt: self.check_payout(
                psbt, recipients, max_fee_sats=max_fee_sats, fee_paid_by=fee_paid_by
            ),
        )

    def finalize_sweep(
        self, unsigned: str, signed: list[str], destination: str, *, max_fee_sats: int
    ) -> SignedPayout:
        """Like finalize, for a refresh or move to `destination`."""
        return self._finish(
            unsigned,
            signed,
            lambda psbt: self.check_sweep(psbt, destination, max_fee_sats=max_fee_sats),
        )

    def _finish(self, unsigned: str, signed: list[str], check) -> SignedPayout:
        combined = _parse(unsigned)
        txid = str(combined.extract_tx_unchecked_fee_rate().compute_txid())
        for copy in signed:
            part = _parse(copy)
            if str(part.extract_tx_unchecked_fee_rate().compute_txid()) != txid:
                raise ClanWalletError("A signature belongs to a different payment")
            combined = combined.combine(part)
        check(combined.serialize())
        # BDK checks every signature here and names the keys whose signature failed.
        result = combined.finalize()
        if not result.could_finalize:
            reasons = " ".join(str(error) for error in result.errors or [])
            raise SignatureError(
                "The payment does not have the required signatures yet",
                tuple(dict.fromkeys(BAD_SIGNATURE.findall(reasons))),
            )
        raw_hex = bytes(result.psbt.extract_tx().serialize()).hex()
        return SignedPayout(txid=txid, raw_hex=raw_hex, fee_sats=result.psbt.fee())


def _base58check(payload: bytes) -> str:
    data = payload + hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    number, text = int.from_bytes(data, "big"), ""
    while number:
        number, digit = divmod(number, 58)
        text = BASE58[digit] + text
    return "1" * (len(data) - len(data.lstrip(b"\0"))) + text


def _parse(psbt_base64: str) -> bdk.Psbt:
    try:
        base64.b64decode(psbt_base64, validate=True)
        return bdk.Psbt(psbt_base64)
    except Exception as exc:
        raise ClanWalletError("The payment data is not a valid PSBT") from exc
