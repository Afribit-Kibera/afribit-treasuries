import { Address } from "@scure/btc-signer";
import { api } from "./live-api";
import { NETWORKS, networkRules, parseKey, type ClanNetwork, type ClanPolicy } from "./vault/policy";
export type WalletPolicy = {
  network: ClanNetwork;
  oversight: string[];
  signers: string[];
  recovery_threshold: number;
  recovery_blocks: number;
};
export type WalletStatus =
  "not_started" | "collecting_keys" | "confirming" | "active" | "retired";
export type WalletStartReason =
  | "lost_key"
  | "stolen_phone"
  | "signatory_change"
  | "oversight_change"
  | "other";
export interface WalletGeneration {
  status: WalletStatus;
  generation: number | null;
  network: ClanNetwork;
  signer_count: number;
  threshold: number;
  recovery_threshold: number;
  recovery_blocks: number;
  recovery_days: number;
  /** Confirmations a payment needs before it counts. */
  confirmations_required?: number;
  oversight_keys: string[];
  signers: {
    user_id: string;
    display_name: string;
    key_registered: boolean;
    fingerprint: string | null;
    confirmed: boolean;
  }[];
  me: { is_signer: boolean; key: string | null; confirmed: boolean };
  policy: WalletPolicy | null;
  wallet_code: string | null;
  activated_at: string | null;
  started_by: string | null;
  start_reason: WalletStartReason | null;
}
export interface WalletView extends WalletGeneration {
  enabled: boolean;
  alarms_recent?: number;
  next: WalletGeneration | null;
  earlier: {
    generation: number;
    wallet_code: string;
    retired_at: string | null;
    balance_sats: number | null;
  }[];
}
export type PayoutPreview = {
  address: string;
  approved_sats: number;
  fee_paid_by: "recipients";
  estimated_fee_sats: number;
  estimated_received_sats: number;
  fee_rate_sat_vb: number;
};
export type AddressPurpose = "contribution" | "repayment" | "grant_funding";
export type WalletAddress = {
  address: string;
  keychain: "external";
  index: number;
  purpose: AddressPurpose;
  grant_id: string | null;
};
export type PayoutStatus =
  | "awaiting_signatures"
  | "awaiting_oversight"
  | "broadcasting"
  | "broadcast"
  | "confirmed"
  | "replaced"
  | "expired";
export interface PayoutDraft {
  id: string;
  clan_id: string;
  kind: "grant" | "move" | "refresh";
  generation: number;
  destination: {
    generation: number;
    keychain: "internal";
    index: number;
    address: string;
  } | null;
  replaces: string | null;
  replaced_by: string | null;
  status: PayoutStatus;
  psbt: string;
  txid: string;
  fee_paid_by: "recipients" | "clan";
  fee_sats: number;
  max_fee_sats: number;
  fee_rate_sat_vb: number;
  recipients: {
    grant_id: string;
    name: string;
    address: string;
    approved_sats: number;
    received_sats: number;
  }[];
  signatures: {
    count: number;
    required: number;
    signed_by_me: boolean;
    names: string[];
  };
  oversight_signed: boolean;
  created_at: string;
  broadcast_txid: string | null;
  confirmations: number;
}
export type TillView = {
  enabled: boolean;
  balance_sats: number;
  cap_sats: number;
  sweep_at_sats: number;
  last_sweep: { txid: string; amount_sats: number; at: string } | null;
};
export const walletPath = (id: string) =>
  `/clans/${encodeURIComponent(id)}/wallet`;
export const getWallet = (id: string) => api<WalletView>(walletPath(id));
export type WalletAlarm = {
  id: string;
  kind: string;
  reference: string;
  clan_id: string;
  generation: number | null;
  created_at: string;
  members: boolean;
  message: string;
  detail: Record<string, unknown>;
};
export const getWalletAlarms = (id: string) =>
  api<WalletAlarm[]>(walletPath(id) + "/alarms");
export const registerWalletKey = (id: string, key: string) =>
  api<WalletView>(walletPath(id) + "/keys", { key });
export const confirmWallet = (id: string, code: string) =>
  api<WalletView>(walletPath(id) + "/confirm", { wallet_code: code });
export const startNextWallet = (id: string, reason: WalletStartReason) =>
  api<WalletView>(walletPath(id) + "/next", { reason });
export const cancelNextWallet = (id: string) =>
  api<WalletView>(walletPath(id) + "/next/cancel", {});
export function walletGeneration(
  view: WalletView,
  generation: number | null,
): WalletView {
  if (view.generation === generation) return view;
  if (view.next?.generation === generation)
    return {
      ...view.next,
      enabled: view.enabled,
      next: null,
      earlier: view.earlier,
    };
  throw Error("The wallet changed. Refresh and compare its code again.");
}
export const setPayoutAddress = (id: string, grant: string, address: string) =>
  api<PayoutPreview>(
    `/clans/${encodeURIComponent(id)}/grants/${encodeURIComponent(grant)}/payout-address`,
    { address },
  );
export const getPayoutQuote = (id: string, grant: string, address: string) =>
  api<PayoutPreview>(
    `/clans/${encodeURIComponent(id)}/grants/${encodeURIComponent(grant)}/payout-quote?` +
      new URLSearchParams({ address }),
  );
export type WalletReceipt = {
  id: string;
  txid: string;
  vout: number;
  address: string;
  purpose: AddressPurpose;
  grant_id: string | null;
  amount_sats: number;
  confirmations: number;
  status: "pending" | "confirmed" | "dropped";
  /** Repayments of a KES debt: the rate used and the KES counted, once credited. */
  kes_per_btc?: string | null;
  kes_credited_minor?: number | null;
  kes_owed_after_minor?: number | null;
  /** Why a confirmed payment isn't counted yet. */
  credit_note?: "waiting_for_rate" | null;
};
export const getWalletReceipts = (id: string, address?: string) =>
  api<WalletReceipt[]>(
    walletPath(id) +
      "/receipts" +
      (address ? "?" + new URLSearchParams({ address }) : ""),
  );
export const getWalletAddress = (
  id: string,
  purpose: AddressPurpose,
  grant?: string,
) =>
  api<WalletAddress>(
    walletPath(id) +
      "/address?" +
      new URLSearchParams({ purpose, ...(grant ? { grant_id: grant } : {}) }),
  );
export const getPayouts = (
  id: string,
  filters: { status?: PayoutStatus | PayoutStatus[]; grantId?: string } = {},
) =>
  api<PayoutDraft[]>(
    walletPath(id) +
      "/payouts?" +
      new URLSearchParams({
        ...(filters.status
          ? { status: [filters.status].flat().join(",") }
          : {}),
        ...(filters.grantId ? { grant_id: filters.grantId } : {}),
      }),
  );
export const getPayout = (id: string, payout: string) =>
  api<PayoutDraft>(walletPath(id) + "/payouts/" + encodeURIComponent(payout));
export const submitPayoutSignature = (
  id: string,
  payout: string,
  psbt: string,
) =>
  api<PayoutDraft>(
    walletPath(id) + "/payouts/" + encodeURIComponent(payout) + "/signature",
    { psbt },
  );
export const getTill = (id: string) =>
  api<TillView>(`/clans/${encodeURIComponent(id)}/till`);
/** What the wallet's coins are: real bitcoin on mainnet, valueless test coins otherwise. */
export const networkLabel = (network: ClanNetwork | undefined) =>
  network === "bitcoin" ? "Bitcoin" : "Test network";
export function toClanPolicy(policy: WalletPolicy): ClanPolicy {
  if (!policy || !NETWORKS.includes(policy.network))
    throw Error(
      "This phone cannot check this wallet's network. Do not use it.",
    );
  return {
    network: policy.network,
    oversight: policy.oversight.map(parseKey),
    signers: policy.signers.map(parseKey),
    recoveryThreshold: policy.recovery_threshold,
    recoveryBlocks: policy.recovery_blocks,
  };
}
export function validatePayoutAddress(
  address: string,
  network: ClanNetwork,
): string {
  try {
    Address(networkRules(network).addresses).decode(address.trim());
    return address.trim();
  } catch {
    throw Error(
      network === "bitcoin"
        ? "Use a Bitcoin address (it starts with bc1, 1 or 3). This address cannot be used."
        : "Use a Bitcoin address from the test network. This address cannot be used.",
    );
  }
}
export function safeSats(value: unknown): bigint {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0)
    throw Error("This payment has an invalid amount. Do not sign it.");
  return BigInt(value);
}
