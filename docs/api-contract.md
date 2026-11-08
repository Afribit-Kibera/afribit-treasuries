# Clans API contract: foundation v0.1.0

**Status:** Implemented local/internal prototype. The machine-readable [OpenAPI contract](openapi.json) is generated from the running code. Verify it with `scripts/export_openapi.py --check` after changes.

Base URL for this milestone: `http://127.0.0.1:8017`. Routes use `/api/v1` except liveness at `/health`. The server also serves `/openapi.json` and interactive documentation at `/docs`.

## Identity and scope

Business routes require `Authorization: Bearer <demo-user-token>`. Random fixture tokens are available only in ignored `.local/demo-identities.json`. They are hashed in the database. Responses never return bearer tokens or token hashes.

This authentication is an internal test facility, explicitly enabled through `CLANS_DEMO_AUTH_ENABLED=true`. It is not passkey authentication, a production sign-in flow or financial authorization. There are no default passwords or hard-coded working tokens. Inactive users and users not marked synthetic cannot authenticate through it. It is disabled by default, returning `503 demo_auth_disabled`.

## Implemented routes

| Method | Route | Access and behavior |
| --- | --- | --- |
| GET | `/health` | Public liveness; reports simulation, demo-auth setting, version and disabled execution. Does not assert database or treasury readiness. |
| GET | `/api/v1/me` | Current synthetic user's public identity. |
| GET | `/api/v1/clans` | Only clans in which the current user has active membership. |
| POST | `/api/v1/clans` | Create a clan, initial policy version, organizer membership and audit event in one transaction. Creator is not automatically a signer. |
| GET | `/api/v1/clans/{clan_id}` | Current clan and policy; active members only. |
| GET | `/api/v1/clans/{clan_id}/members` | Active members and their roles; active members only. |
| GET | `/api/v1/system/btcpay/health` | Authenticated, read-only provider health. Sends no provider credentials and never executes a payment. |

List endpoints accept `limit` (1-100, default 50) and `offset` (zero or higher, default 0). They return arrays, ordered consistently. Clan ordering is creation timestamp then ID; member ordering is display name then user ID.

## Create a clan

```http
POST /api/v1/clans
Authorization: Bearer <demo-user-token>
Content-Type: application/json

{
  "name": "Test Savings Circle",
  "policy": {
    "currency": "KES",
    "member_vote_quorum": 3,
    "signer_threshold": 2,
    "beneficiary_can_approve": false
  }
}
```

Successful response: `201 Created`.

```json
{
  "id": "7d7a270f-d6c1-40ea-8c9b-a119d9a7d2cc",
  "name": "Test Savings Circle",
  "status": "active",
  "created_at": "2026-11-02T13:45:00+00:00",
  "policy": {
    "id": "26c7738f-e0b7-4f6d-8eab-d9294095bab9",
    "version": 1,
    "currency": "KES",
    "member_vote_quorum": 3,
    "signer_threshold": 2,
    "beneficiary_can_approve": false
  },
  "member_count": 1,
  "signer_count": 0,
  "governance_ready": false,
  "payment_mode": "simulation"
}
```

IDs and timestamp above are illustrative. Names are trimmed and must contain visible text, maximum 100 characters. Currencies are `KES` or `BTC`; quorum and threshold are positive integers, maximum 1000 and 100 respectively. Unknown fields, numeric strings and boolean thresholds are rejected. Defaults are KES, member quorum 1, signer threshold 2 and beneficiary approval disallowed.

`governance_ready` checks only whether the current active roster meets the initial quorum and signer counts. It does not establish vote eligibility for a particular grant, enforce a vote, verify signatures or enable spending. An incomplete roster may exist while membership is being arranged. There is no membership mutation API yet; fixture membership is seeded internally.

Clan creation has no BTCPay or channel-balance dependency. An unfunded clan can be created even while BTCPay is unavailable; liquidity gates actual payments separately. Clans are application records and do not each require a new Lightning channel. Real multi-clan treasury allocation/accounting remains to be implemented.

Signer rosters are not limited to three. The owner wants 3, 5 or 7 signers as onboarding choices, with selectable approval thresholds. Local API simulations now verify 2-of-3, 3-of-5 and 4-of-7: one fewer approval fails, the selected threshold succeeds, and added synthetic signers participate. These are candidate majority defaults, not a hard-coded limit or a completed onboarding picker. `signer_threshold` sets approvals required; `signer_count` reports actual active signer memberships. Selecting/inviting/removing signers and governed policy changes still need implementation. The creator is not automatically a signer, and beneficiary conflict rules continue to apply.

This create endpoint currently has no idempotency contract. Do not retry it automatically after an uncertain response; it can create another clan. Financial operations will require durable idempotency before they are implemented.

## Errors

Implemented handler errors use this envelope:

```json
{
  "error": {
    "code": "clan_not_found",
    "message": "Clan was not found"
  }
}
```

| Status | Code | Client action |
| --- | --- | --- |
| 401 | `unauthorized` | Supply a valid active fixture user's bearer token. |
| 404 | `clan_not_found` | No accessible clan; the API does not distinguish missing clans from outsider access. |
| 422 | `validation_error` | Correct request fields, bounds or money-independent policy values. |
| 503 | `demo_auth_disabled` | Internal environment has not enabled fixture authentication. |
| 503 | `provider_unavailable` | Provider health was not verifiable; do not imply readiness. |

Provider redirects, errors, timeouts and malformed responses are not successful health checks. A successful provider response may still have `synchronized: false`. Provider health always returns `execution_enabled: false`.

## Simulation API

Implemented only when `CLANS_SIMULATION_ENABLED=true`, alongside demo authentication. All responses identify `mode: "simulation"` and `real_payments_enabled: false`. The simulation makes no wallet calls and cannot turn an invoice or user-supplied claim into real treasury funds. Production financial operations remain separate work.

| Method | Route | Behavior |
| --- | --- | --- |
| POST | `/api/v1/clans/{clan_id}/simulations` | Start a run with `{ "name": "Circular grant demonstration" }`, snapshotting policy and roster. Name is optional. |
| GET | `/api/v1/clans/{clan_id}/simulations/{run_id}` | Read accessible run, revision, balances, grants, simulated journal and events. |
| POST | `/api/v1/clans/{clan_id}/simulations/{run_id}/commands` | Apply one typed command atomically and return the updated run. |

Both POST routes require `Idempotency-Key`, 1–100 characters, scoped to the actor and run (creation is scoped to actor and clan). Retry the exact same request with the same key to receive the original response without repeating it. A changed request with that key returns `409 idempotency_conflict`. A concurrent revision conflict returns `409`; read current state before deciding whether to retry. Keys for new commands must be new.

Command bodies are a discriminated union on `action`; see OpenAPI for exact schemas, bounds and required fields. Unknown fields are rejected. Satoshi amounts are strict integers.

| Action | Main fields | Rule |
| --- | --- | --- |
| `contribute` | `amount_sats` | Adds simulated capital only. |
| `request_grant` | `amount_sats`, `purpose`, optional `obligation_currency` | Applicant is the authenticated member. Currency defaults to BTC; KES uses a fixture valuation. |
| `vote` | `grant_id`, `choice` | `approve`, `reject` or `abstain`; one vote per eligible member. |
| `accept_terms` | `grant_id` | Beneficiary accepts an approved grant. |
| `freeze_intent` | `grant_id`, `destination`, optional fee ceiling/expiry | Signer reserves principal plus maximum fees and freezes an expiring hash. Destinations must start `sim:`. Changing it clears approvals. |
| `approve_intent` | `grant_id`, `intent_sha256` | Eligible signer approves that exact current hash. Member votes do not count as signer approvals. |
| `execute` | `grant_id`, `intent_sha256`, optional `actual_fee_sats` | Simulates issuance after rechecking quorum, eligibility, expiry, balance and fee limit. Never sends a payment. |
| `cancel_intent` | `grant_id` | Signer releases a pending intent's reservation. |
| `repay` | `grant_id`, `amount_sats`, `settlement_reference`, optional `method`, `remitter_user_id` | Beneficiary records simulated repayment. Method is `lightning` or `otc`; OTC requires a synthetic remitter. References start `sim:` and cannot be credited twice. |
| `propose_amendment` | `grant_id`, `new_outstanding_minor`, `reason` | Proposes reducing the obligation; never erases original disbursement or repayment history. |
| `vote_amendment` | `grant_id`, `amendment_id`, `choice` | Eligible members vote on the reduction using the snapshotted quorum. |

`state.balance_sats`, `reserved_sats` and `available_sats` describe this run only; available equals balance minus reservations. Journal debit/credit amounts balance and reconcile to the simulated treasury. These figures are not node liquidity. Failed commands leave state unchanged. Outsiders cannot read a run. Execution checks the live active roster as well as the snapshot, so a removed signer or voter cannot continue satisfying a quorum.

BTC obligation minor units are sats; KES minor units are cents. `kes_minor_per_1000_sats` is a fixed simulation fixture applied to principal and repayments, with integer rounding. It is not a market quote. Forgiveness reduces an obligation without adding treasury funds. OTC records keep beneficiary and remitter separate, but do not verify an actual trade or payment.

Errors use the existing envelope. Disabled simulation returns `503 simulation_disabled`; inaccessible runs return `404`; schema errors return `422`; invalid transitions, insufficient funds, stale intents and duplicate settlements return `409` with a specific code/message. Refresh run state after a conflict. This slice uses synthetic bearer attestations, application-enforced journals and SQLite; it does not establish cryptographic multisig, independent node-spending controls or PostgreSQL concurrency readiness.

## Not implemented

Invitations and membership changes, passkeys, real contributions and financial journals, real grant issuance/repayment matching, OTC settlement verification, webhooks and payment execution remain future slices. The simulation above demonstrates selected domain behavior only. The application audit and simulation journal are not a tamper-proof external audit service.

PostgreSQL migrations, PostgreSQL-backed integration tests, CORS integration and production deployment also remain outstanding. Frontend developers can use this contract for identity and clan-read integration against the internal prototype while later contracts are developed from the owner's test scenarios.
