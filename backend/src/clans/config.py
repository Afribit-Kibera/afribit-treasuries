from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CLANS_", extra="ignore", hide_input_in_errors=True
    )

    database_url: SecretStr = SecretStr("sqlite+pysqlite:///.local/clans-demo.db")
    demo_auth_enabled: bool = False
    simulation_enabled: bool = False
    payment_mode: Literal["simulation"] = "simulation"
    btcpay_url: str = "https://pay.insats.org"
    btcpay_api_key: SecretStr = SecretStr("")
    btcpay_store_id: str = ""
    provider_timeout_seconds: float = Field(default=10, gt=0, le=30)

    @model_validator(mode="after")
    def validate_provider_url(self) -> "Settings":
        parsed = urlparse(self.btcpay_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
        ):
            raise ValueError("BTCPay URL must be an HTTPS origin without credentials")
        return self

    def prepare_local_directory(self) -> None:
        url = self.database_url.get_secret_value()
        if url.startswith("sqlite+pysqlite:///."):
            Path(url.removeprefix("sqlite+pysqlite:///")).parent.mkdir(parents=True, exist_ok=True)
