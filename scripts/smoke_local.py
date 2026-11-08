"""Exercise the running loopback API; fixture credentials never enter output."""

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx


def main() -> int:
    fixture = json.loads(
        Path(".local/demo-identities.json").read_text(encoding="utf-8")
    )
    results = []
    with httpx.Client(
        base_url="http://127.0.0.1:8017", timeout=15, follow_redirects=False
    ) as client:
        health = client.get("/health")
        results.append(
            {
                "check": "liveness_simulation_only",
                "passed": (
                    health.status_code == 200
                    and health.json().get("payment_mode") == "simulation"
                    and health.json().get("payment_execution_enabled") is False
                ),
            }
        )
        for persona, user in fixture["users"].items():
            headers = {"Authorization": "Bearer " + user["bearer_token"]}
            identity = client.get("/api/v1/me", headers=headers)
            results.append(
                {
                    "check": "identity_" + persona,
                    "passed": (
                        identity.status_code == 200
                        and identity.json().get("id") == user["id"]
                    ),
                }
            )
            clan = client.get("/api/v1/clans/" + fixture["clan_id"], headers=headers)
            roster = client.get(
                "/api/v1/clans/" + fixture["clan_id"] + "/members", headers=headers
            )
            outsider = persona == "otc_merchant"
            results.append(
                {
                    "check": "clan_access_" + persona,
                    "passed": (
                        clan.status_code == (404 if outsider else 200)
                        and roster.status_code == (404 if outsider else 200)
                    ),
                }
            )
            if not outsider and clan.status_code == 200:
                results.append(
                    {
                        "check": "roster_policy_" + persona,
                        "passed": (
                            clan.json().get("member_count") == 5
                            and clan.json().get("signer_count") == 3
                            and clan.json().get("policy", {}).get("signer_threshold")
                            == 2
                            and len(roster.json()) == 5
                        ),
                    }
                )
        unauthorized = client.get("/api/v1/clans")
        results.append(
            {
                "check": "unauthenticated_rejected",
                "passed": unauthorized.status_code == 401,
            }
        )
        headers = {
            "Authorization": "Bearer " + fixture["users"]["chair"]["bearer_token"]
        }
        provider = client.get("/api/v1/system/btcpay/health", headers=headers)
        results.append(
            {
                "check": "live_btcpay_read_only_health",
                "passed": (
                    provider.status_code == 200
                    and provider.json()
                    == {
                        "reachable": True,
                        "synchronized": True,
                        "execution_enabled": False,
                    }
                ),
            }
        )
    passed = all(item["passed"] for item in results)
    output = Path("docs/test-results/2026-11-02-local-api-smoke.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "observed_at_utc": datetime.now(UTC).isoformat(),
                "test_id": "BE-001-SMOKE",
                "result": "passed" if passed else "failed",
                "checks": results,
                "payment_execution": False,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        f"Local API smoke: {sum(item['passed'] for item in results)}/{len(results)} checks passed."
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
