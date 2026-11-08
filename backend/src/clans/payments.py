"""Read-only BTCPay probe. No invoice creation or spending methods exist yet."""

import httpx

from clans.schemas import ProviderHealth


class ProviderUnavailable(Exception):
    pass


class BtcpayProbe:
    def __init__(self, base_url: str, timeout: float = 10):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def health(self, *, transport: httpx.BaseTransport | None = None) -> ProviderHealth:
        try:
            with httpx.Client(
                base_url=self.base_url,
                timeout=self.timeout,
                follow_redirects=False,
                transport=transport,
            ) as client:
                response = client.get("/api/v1/health")
                response.raise_for_status()
                body = response.json()
                if not isinstance(body, dict) or type(body.get("synchronized")) is not bool:
                    raise ProviderUnavailable("Provider returned an invalid health response")
                return ProviderHealth(reachable=True, synchronized=body["synchronized"])
        except (httpx.HTTPError, ValueError) as exc:
            # Provider URLs, response bodies and credentials never enter API error messages.
            raise ProviderUnavailable("Provider health could not be verified") from exc
