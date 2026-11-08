export type Persona = { key: string; id: string; display_name: string };
export type Session = {
  clan_id: string;
  run_id: string;
  personas: Persona[];
  mode: "simulation";
};
export type Clan = {
  id: string;
  name: string;
  status: string;
  member_count: number;
  signer_count: number;
  governance_ready: boolean;
  policy: {
    signer_threshold: number;
    member_vote_quorum: number;
    currency: "KES" | "BTC";
    beneficiary_can_approve: boolean;
  };
};
export type Member = {
  user: { id: string; display_name: string; is_test_user: boolean };
  role: string;
  is_signer: boolean;
};
export type Grant = {
  id: string;
  beneficiary_id: string;
  purpose: string;
  amount_sats: number;
  status: string;
  obligation_currency: "KES" | "BTC";
  outstanding_minor: number;
  principal_minor: number;
  forgiven_minor: number;
  recovered_sats: number;
  votes: Record<string, string>;
  eligible_voter_ids: string[];
  eligible_signer_ids: string[];
  approvals: string[];
  intent: null | {
    sha256: string;
    expires_at: string;
    destination: string;
    fee_ceiling_sats: number;
  };
  repayments: {
    sats: number;
    credited_minor: number;
    method: string;
    remitter_id: string;
    beneficiary_id: string;
    reference: string;
    settled_at: string;
  }[];
};
export type SimEvent = {
  action: string;
  actor_id: string;
  at: string;
  grant_id: string | null;
};
export type Run = {
  id: string;
  clan_id: string;
  revision: number;
  mode: "simulation";
  real_payments_enabled: false;
  state: {
    available_sats: number;
    balance_sats: number;
    reserved_sats: number;
    contributed_sats: number;
    disbursed_sats: number;
    recovered_sats: number;
    fees_sats: number;
    grants: Record<string, Grant>;
    events: SimEvent[];
    journal: unknown[];
  };
};
