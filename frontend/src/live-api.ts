export interface ClanSummary {
  id: string;
  name: string;
  description: string;
  target_signers: number;
  signer_threshold: number;
  member_vote_quorum: number;
  signer_count: number;
  member_count: number;
  governance_ready: boolean;
  balance_sats: number;
  reserved_sats: number;
  available_sats: number;
  balance_msat: string;
  reserved_msat: string;
  available_msat: string;
  in_recovery_msat: string;
  grants_given_msat: string;
  grants_repaid_msat: string;
  created_at: string;
  /** Who oversees the clan's wallet payments. id null: the default community, Afribit. */
  community?: { id: string | null; name: string };
}
export interface Member {
  id: string;
  name: string;
  handle: string;
  role: string;
  is_signer: boolean;
}
export interface Grant {
  id: string;
  beneficiary_id: string;
  beneficiary_name: string;
  purpose: string;
  amount_sats: number;
  status: string;
  created_at: string;
  accepted_at: string | null;
  required_votes: number;
  votes: { user_id: string; choice: string }[];
  can_vote: boolean;
  outstanding_msat: string;
  recovered_msat: string;
  /** "KES": the debt is KES, and the two amounts below are KES cents. "BTC": sats. */
  obligation_currency?: "KES" | "BTC";
  principal_minor?: number;
  /** What is still owed, in the debt's currency. 0 before the grant is paid. */
  outstanding_minor?: number;
  recovered_sats?: number;
  /** About what is still owed in sats now. null when no fresh rate is available. */
  outstanding_sats_estimate?: number | null;
  payment: PaymentIntent | null;
}
export interface PaymentIntent {
  id: string;
  digest: string;
  payment_hash: string;
  status: string;
  expires_at: string;
  amount_msat: string;
  fee_limit_msat: string;
  fee_paid_msat: string | null;
  approval_count: number;
  required_approvals: number;
  approved_by_me: boolean;
  can_approve: boolean;
  payout_status: string | null;
  last_error: string | null;
  approved_names: string[];
  account_recovery_pending: boolean;
}
export interface AccessRecovery {
  id: string;
  member_name: string;
  member_id: string;
  created_at: string;
  status: string;
  ready_at: string | null;
  approvals: number;
  required: number;
  approved_names: string[];
  can_approve: boolean;
}
export interface Deposit {
  requested_by_me?: boolean;
  id: string;
  clan_id: string;
  grant_id: string | null;
  amount_sats: number;
  status: string;
  bolt11: string | null;
  checkout_url: string | null;
  expires_at: string | null;
  credited_sats: number;
  created_at: string;
}
export type ActivityCategory =
  | "clan"
  | "members"
  | "grants"
  | "money"
  | "wallet"
  | "security"
  | "account";
/** One row of `GET /clans/{id}/activity`. */
export interface ActivityItem {
  id: string;
  event: string;
  actor: string;
  at: string;
  /** Sent by current servers. An older server sends only `event`. */
  title?: string;
  category?: ActivityCategory;
  summary?: string;
  data: Record<string, unknown>;
}
/** `GET /clans/{id}/activity/{event_id}`: one event explained. */
export interface ActivityDetail {
  id: string;
  event: string;
  actor: string;
  at: string;
  title: string;
  category: ActivityCategory;
  summary: string;
  details: { label: string; value: string }[];
  links: { grant_id?: string; payout_id?: string; txid?: string };
}
export interface ClanDetail extends ClanSummary {
  my_role: string;
  my_signer: boolean;
  members: Member[];
  grants: Grant[];
  invitations: {
    id: string;
    is_signer: boolean;
    expires_at: string;
    accepted: boolean;
    revoked: boolean;
  }[];
  activity: ActivityItem[];
  journal: { id: string; event: string; amount_msat: string; at: string }[];
  deposits: Deposit[];
  treasury_ready: boolean;
  access_recoveries: AccessRecovery[];
}
export interface Session {
  user: {
    id: string;
    display_name: string;
    handle: string;
    onboarded: boolean;
    phone_number: string | null;
    lightning_address: string | null;
    contact_complete: boolean;
    clan_recovery_enabled: boolean;
  } | null;
  clans?: ClanSummary[];
  csrf: string | null;
  custody_notice: string;
  terms_version: string;
  capabilities: {
    receiving: boolean;
    payouts: boolean;
    currency: string;
    max_invoice_sats: number;
    max_payout_sats: number;
    payout_budget_currency?: "SATS" | "KES";
    payout_global_24h_kes?: number;
    payout_clan_24h_kes?: number;
    max_payout_kes?: number;
  };
}
let csrf: string | null = null;
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}
export async function api<T>(
  path: string,
  body?: unknown,
  key?: string,
  recoveryCsrf?: string,
): Promise<T> {
  const headers: Record<string, string> = {};
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    if (csrf) headers["X-CSRF-Token"] = csrf;
    if (recoveryCsrf) headers["X-Recovery-CSRF-Token"] = recoveryCsrf;
    if (key) headers["Idempotency-Key"] = key;
  }
  const response = await fetch(`/api${path}`, {
    signal: AbortSignal.timeout(20_000),
    method: body === undefined ? "GET" : "POST",
    credentials: "same-origin",
    cache: "no-store",
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401)
      window.dispatchEvent(new Event("clans-session-expired"));
    const detail = result.detail;
    throw new ApiError(
      typeof detail === "string"
        ? detail
        : response.status === 422
          ? "Check the fields and try again."
          : "Clans could not complete this request. Please try again.",
      response.status,
    );
  }
  return result;
}
export const getActivityDetail = (clanId: string, eventId: string) =>
  api<ActivityDetail>(
    `/clans/${encodeURIComponent(clanId)}/activity/${encodeURIComponent(eventId)}`,
  );
export async function getSession(): Promise<Session> {
  const session = await api<Session>("/session");
  csrf = session.csrf;
  return session;
}
