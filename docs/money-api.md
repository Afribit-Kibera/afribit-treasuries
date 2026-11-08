# Production money API — 1.4.0

Accounts have chosen usernames and 12 recovery words, and a member has one active clan at a time.

Paths below are under `/api`. Use the application session cookie. Fetch `/session` for CSRF and capabilities. POST requires JSON, exact Origin and `X-CSRF-Token`. Deposit creation and destination submission also require a stable16–100 character `Idempotency-Key`. Preserve it across transport retries; reuse with another body returns 409.

User inputs use integer sats. Response fields ending `_msat` are **decimal strings containing integer millisatoshis**. Use integer arithmetic and preserve up to three fractional sat digits. No floating-point fiat conversion is implied. Provider keys and settlement preimages never belong in client responses.

## Deposit and recovery

`POST /clans/{clan}/deposits`

```json
{"amount_sats":1000,"grant_id":null}
```

Returns `{"request_id":"<uuid>"}`. Supply a disbursed grant's ID for repayment. Membership, outstanding debt where applicable, limits and worker heartbeat are checked. Poll `GET /clans/{clan}/deposits/{request}` every five seconds:

```json
{
  "id":"<uuid>","clan_id":"<uuid>","grant_id":null,
  "amount_sats":1000,"status":"pending",
  "bolt11":"<verified mainnet invoice>",
  "checkout_url":"https://pay.insats.org/i/<invoice>",
  "expires_at":"<UTC ISO8601>","credited_sats":0,"created_at":"<UTC ISO8601>"
}
```

States: `creating` → `creating_provider` → `pending` → `settled`. Ambiguous creation becomes `reconciling`; the worker searches its immutable order ID and never blindly POSTs another invoice. Expired unpaid invoices become `expired` and remain checked for late settlements. Invoice/checkout/expiry can be null while preparing. A settled response contains actual credited sats.

Render QR `lightning:<bolt11>`, wallet link, copy action and the verified HTTPS checkout link. Hide payment actions after expiry/settlement. On connection loss, retain the request ID and resume checking; do not ask for a second payment. Clan detail includes the 20 latest deposit requests for reopening after refresh.

Confirmed repayment reduces outstanding principal up to zero; surplus becomes clan capital. Partial repayments are supported. The frontend never directly credits a balance or reduces debt.

## Receiving invoice and reservation

After member approval and beneficiary acceptance, only the beneficiary calls:

`POST /clans/{clan}/grants/{grant}/destination`

```json
{"bolt11":"<external mainnet fixed-amount invoice>"}
```

Returns `{"intent_id":"<uuid>"}`. The server checks signature, exact grant amount, external payee and expiry. Enough settled capital for principal plus fee cap is required. A canonical payment intent reserves those funds. Replacing an unpaid intent releases its reservation and invalidates signatures. Queued, in-flight or uncertain payments cannot be replaced/withdrawn.

`GET /clans/{clan}/grants/{grant}/payment` returns the latest intent or null:

```json
{
  "id":"<uuid>","digest":"<sha256>","payment_hash":"<hash>",
  "status":"awaiting_approvals","expires_at":"<UTC ISO8601>",
  "amount_msat":"100000","fee_limit_msat":"1000","fee_paid_msat":null,
  "approval_count":0,"required_approvals":2,"approved_by_me":false,
  "can_approve":true,"payout_status":null,"last_error":null
}
```

Show beneficiary, amount, fee cap, expiry, approval progress and payment hash before signing. **Reaching the threshold automatically queues payment.**

## Passkey sign-off

1. `POST .../payment/approval/options` with `{}` returns `challenge_id`, WebAuthn `options` and `intent`. Compare that digest with the reviewed payment; refresh if changed.
2. Call `startAuthentication({optionsJSON: options})` from `@simplewebauthn/browser`.
3. `POST .../payment/approval/verify` with `{"challenge_id":"<uuid>","credential":<assertion>}` returns `status` and `approvals`.

Challenges bind the exact intent and fresh nonce. User verification, current credential ownership and signer eligibility are required. Ordinary login assertions and grant votes cannot approve payment. Recovery revokes old-key approvals; the current key must approve again.

Intent statuses include `awaiting_approvals`, `queued`, `sending`, `settled`, `failed`, `expired`, `superseded` and `rejected`. `payout_status` additionally exposes `uncertain` and `awaiting_approvals`. Poll while awaiting results. Grants move through `awaiting_signatures`, `payment_queued`, `paying`, then `in_recovery`. A confirmed failure returns a grant to `awaiting_funding`; complete repayment yields `recovered`.

An uncertain payment keeps its reservation until node proof resolves it. Never release funds or submit a new destination from the client after a timeout. Safe error codes:

| Code | Meaning |
|---|---|
| `payment_failed_no_route_or_liquidity` | Node confirmed failure; reservation released. |
| `waiting_for_node_confirmation` | Outcome pending; keep waiting. |
| `operator_fee_excess_requires_review` | Provider discrepancy; operator review required, clan fee remains capped. |

## State and errors

Clan detail includes exact `balance_msat`, `reserved_msat`, `available_msat`, `in_recovery_msat`, `treasury_ready`, deposits, journal `amount_msat`, and each grant's `outstanding_msat`, `recovered_msat` and `payment`. Legacy `_sats` balance fields are floor-rounded; the UI uses `_msat`. Limits come from session capabilities.

403 indicates Origin/CSRF, membership or action eligibility failure. 409 indicates state/idempotency conflict or insufficient capital. 400/422 indicates invalid input/invoice. 503 indicates disabled movement or unavailable synchronization. Display safe server `detail`, preserve form/idempotency key on a transport error, and clear private account UI on 401. Never cache API data or queue financial mutations offline.

Fee units and pending-response reconciliation follow the [BTCPay Greenfield API](https://docs.btcpayserver.org/API/Greenfield/v1/). The worker verifies actual receipts and settlement preimages independently of a successful POST response.
