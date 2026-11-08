import httpx
import pytest

from clans.payments import BtcpayProbe, ProviderUnavailable


@pytest.mark.parametrize("synchronized", [True, False])
def test_probe_only_gets_health_and_preserves_unsynchronized_state(synchronized):
    def handler(request):
        assert request.method == "GET"
        assert request.url.path == "/api/v1/health"
        assert "authorization" not in request.headers
        return httpx.Response(200, json={"synchronized": synchronized})

    result = BtcpayProbe("https://btcpay.example").health(transport=httpx.MockTransport(handler))
    assert result.reachable is True
    assert result.synchronized is synchronized
    assert result.execution_enabled is False


@pytest.mark.parametrize(
    "status,body",
    [
        (401, {"private": "secret"}),
        (500, {"private": "secret"}),
        (302, {}),
        (200, {}),
        (200, []),
        (200, {"synchronized": "true"}),
    ],
)
def test_probe_fails_closed_on_http_errors_redirects_and_malformed_responses(status, body):
    transport = httpx.MockTransport(lambda request: httpx.Response(status, json=body))
    with pytest.raises(ProviderUnavailable) as caught:
        BtcpayProbe("https://btcpay.example").health(transport=transport)
    assert "secret" not in str(caught.value)


def test_probe_timeout_is_not_reported_as_readiness():
    def timeout(request):
        raise httpx.ReadTimeout("private-provider-data", request=request)

    with pytest.raises(ProviderUnavailable, match="could not be verified") as caught:
        BtcpayProbe("https://btcpay.example").health(transport=httpx.MockTransport(timeout))
    assert "private-provider-data" not in str(caught.value)


def test_api_sanitizes_provider_failure(client, headers, monkeypatch):
    def fail(_self):
        raise ProviderUnavailable("secret from provider")

    monkeypatch.setattr(BtcpayProbe, "health", fail)
    response = client.get("/api/v1/system/btcpay/health", headers=headers())
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "provider_unavailable"
    assert "secret" not in response.text
