"""Production settings are separate from the synthetic demo application."""

from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from clans.explorers import explorer_urls


class LiveSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CLANS_", extra="ignore", hide_input_in_errors=True
    )

    environment: Literal["production", "development", "test"] = "production"
    database_url: SecretStr
    session_secret: SecretStr
    public_origin: str = "https://clans.afribit.africa"
    rp_id: str = "clans.afribit.africa"
    static_directory: Path | None = None
    session_days: int = Field(default=7, ge=1, le=30)
    receiving_enabled: bool = False
    payouts_enabled: bool = False
    btcpay_url: str = "https://pay.insats.org"
    btcpay_store_id: str = ""
    btcpay_api_key: SecretStr = SecretStr("")
    max_invoice_sats: int = Field(default=100_000, ge=1, le=10_000_000)
    max_payout_sats: int = Field(default=100_000, ge=1, le=10_000_000)
    expected_node_pubkey: str = ""
    provider_namespace: str = "clans-production"
    payout_fee_ppm: int = Field(default=10_000, ge=0, le=50_000)
    payout_fee_max_sats: int = Field(default=1_000, ge=1, le=10_000)
    # Worker-only key: never provision this in the web environment or reuse session_secret.
    dispatch_secret: SecretStr = SecretStr("")
    payout_global_24h_sats: int = Field(default=0, ge=0, le=100_000_000)
    payout_clan_24h_sats: int = Field(default=0, ge=0, le=100_000_000)
    payout_budget_currency: Literal["SATS", "KES"] = "SATS"
    payout_global_24h_kes: int = Field(default=0, ge=0, le=100_000_000)
    payout_clan_24h_kes: int = Field(default=0, ge=0, le=100_000_000)
    max_payout_kes: int = Field(default=0, ge=0, le=100_000_000)
    signer_trust_public_key: str = ""
    signer_trust_directory: Path | None = None
    # Always required in production; opt in for explicit development/test checks.
    signer_trust_required: bool = False
    # Clan multisig wallets. Oversight keys are public and comma
    # separated, one per Afribit signing device; any one of them can approve a payout.
    # The private keys live on those devices, never on this server.
    clan_wallets_enabled: bool = False
    # Bitcoin mainnet unless set otherwise. Use signet or testnet4 to try it out. The oversight
    # keys must be made for the same network, so a wrong setting stops the server from starting.
    clan_wallet_network: Literal["signet", "testnet4", "bitcoin"] = "bitcoin"
    # How many confirmations a deposit, repayment or payout needs before it counts.
    clan_wallet_confirmations: int = Field(default=3, ge=1, le=12)
    clan_wallet_oversight_keys: str = ""
    clan_wallet_recovery_blocks: int = Field(default=26_280, ge=4_320, le=65_535)
    # Esplora APIs for the chain watcher, comma separated, tried in order. Empty: the public
    # ones for the network (clans.explorers). Put your own node first.
    clan_wallet_esplora_url: str = ""
    # A wallet with no new block and nothing new from its clan is read this often.
    clan_wallet_idle_read_seconds: int = Field(default=300, ge=30, le=3_600)
    # The most network fee one payout may carry. Oversight laptops apply their own limit too.
    clan_wallet_max_fee_sats: int = Field(default=2_000, ge=100, le=50_000)
    # The most network fee a refresh or a move to a new wallet may carry. These spend
    # many coins at once, and the clan pays their fee.
    clan_wallet_max_sweep_fee_sats: int = Field(default=10_000, ge=1_000, le=100_000)
    # A sent payout still unconfirmed after this long gets a higher-fee version to sign.
    clan_wallet_bump_after_minutes: int = Field(default=180, ge=30, le=10_080)
    # SHA-256 hashes (hex, comma separated) of each oversight laptop's read token. The token
    # lets a laptop list payouts waiting for Afribit. It can't approve anything. Empty: off.
    clan_wallet_oversight_token_hashes: str = ""
    # The name members see for the community the settings' oversight keys belong to. Other
    # communities, each with their own oversight, are in the database (clans.communities).
    clan_default_community_name: str = Field(default="Afribit", min_length=2, max_length=100)

    @property
    def oversight_token_hashes(self) -> list[str]:
        return [
            value.strip().lower()
            for value in self.clan_wallet_oversight_token_hashes.split(",")
            if value.strip()
        ]

    @property
    def esplora_urls(self) -> list[str]:
        return explorer_urls(self.clan_wallet_network, self.clan_wallet_esplora_url)

    @property
    def oversight_keys(self) -> list[str]:
        return [key.strip() for key in self.clan_wallet_oversight_keys.split(",") if key.strip()]

    @property
    def secure_cookies(self) -> bool:
        return self.public_origin.startswith("https://")

    @property
    def cookie_name(self) -> str:
        return "__Host-clans_session" if self.secure_cookies else "clans_session"

    @property
    def challenge_cookie(self) -> str:
        return "__Host-clans_challenge" if self.secure_cookies else "clans_challenge"

    @model_validator(mode="after")
    def validate_deployment(self):
        origin = urlparse(self.public_origin)
        if origin.path or origin.query or origin.fragment or origin.username:
            raise ValueError("Public origin must be a bare origin")
        if origin.hostname != self.rp_id:
            raise ValueError("Passkey RP ID must match the application hostname")
        if len(self.session_secret.get_secret_value()) < 48:
            raise ValueError("A strong independent Clans session secret is required")
        if self.environment == "production":
            if origin.scheme != "https":
                raise ValueError("Production requires HTTPS")
            if not self.database_url.get_secret_value().startswith("postgresql"):
                raise ValueError("Production requires a dedicated PostgreSQL database")
        elif origin.scheme not in {"https", "http"}:
            raise ValueError("Invalid origin")
        elif origin.scheme == "http" and origin.hostname not in {"localhost", "127.0.0.1"}:
            raise ValueError("HTTP is allowed only on loopback")
        provider = urlparse(self.btcpay_url)
        if (
            provider.scheme != "https"
            or not provider.hostname
            or provider.username
            or provider.path not in {"", "/"}
            or provider.query
            or provider.fragment
        ):
            raise ValueError("BTCPay must use an HTTPS origin")
        if self.receiving_enabled and (
            not self.btcpay_store_id or not self.btcpay_api_key.get_secret_value()
        ):
            raise ValueError("Receiving requires the dedicated store credential")
        if self.clan_wallets_enabled:
            from clans.clan_wallet import ClanWalletError, SignerKey

            explorer_urls(self.clan_wallet_network, self.clan_wallet_esplora_url)

            try:
                keys = [SignerKey.parse(key) for key in self.oversight_keys]
            except ClanWalletError as exc:
                raise ValueError("Clan wallets require Afribit's oversight public keys") from exc
            if not 1 <= len(keys) <= 3 or len({k.fingerprint for k in keys}) != len(keys):
                raise ValueError("Configure one to three different oversight public keys")
            mainnet = self.clan_wallet_network == "bitcoin"
            if any(key.mainnet != mainnet for key in keys):
                raise ValueError(
                    "The oversight keys must be made for the wallet network "
                    "(xpub for mainnet, tpub for test networks)"
                )
        if any(
            len(value) != 64 or set(value) - set("0123456789abcdef")
            for value in self.oversight_token_hashes
        ):
            raise ValueError("Oversight token hashes must be 64 hexadecimal characters")
        return self
