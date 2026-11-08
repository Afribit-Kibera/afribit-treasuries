// What backend/src/clans/oversight_service.py returns, command by command.

export type Network = "bitcoin" | "signet" | "testnet" | "regtest" | string;
export type PayoutKind = "grant" | "refresh" | "move" | string;

export interface Status {
  protocol: number;
  has_key: boolean;
  connected: boolean;
  server: string | null;
  default_server: string | null;
  home: string;
  has_mainnet_key: boolean;
  registered_wallets: number;
}

export interface CreatedKey {
  words: string[];
  public_key: string;
}

export interface RestoredKey {
  public_key: string;
}

export interface Ok {
  ok: true;
}

export interface Connected {
  connection_line: string;
  admin_text: string;
}

export interface AdminLines {
  text: string;
}

export interface Limits {
  max_fee_sats: number;
  max_sweep_fee_sats: number;
  large_payout_sats: number;
  [name: string]: number;
}

export interface Records {
  addresses: { name: string; address: string; confirmed_at: string }[];
  approvals: {
    signed_at: string;
    clan_id: string;
    clan_name: string;
    kind: PayoutKind;
    total_sats: number;
    fee_sats: number;
    txid: string;
  }[];
  settings: Limits;
  register_file: string;
}

export interface Clan {
  clan_id: string;
  clan_name: string;
  generation: number;
  wallet_code: string;
  network: Network;
  threshold: number;
  signers: number;
}

export interface CheckedAddress {
  address: string;
  fixed_start: string;
  check_start: string;
  check_end: string;
}

export type FundingAddress = CheckedAddress;

export interface Alarm {
  created_at: string;
  kind: string;
  message: string;
  clan_id: string | null;
  clan_name: string;
  generation: number | null;
  detail: Record<string, unknown>;
}

export interface WalletToRegister {
  clan_id: string;
  clan_name: string;
  generation: number;
}

export interface PayoutSummary {
  id: string;
  clan_id: string;
  clan_name: string;
  kind: PayoutKind;
  created_at: string | null;
  beneficiaries: string[];
  approved_sats: number;
}

export type Overview =
  | {
      answered: true;
      community: string | null;
      networks: Network[];
      alarms: Alarm[];
      wallets_to_register: WalletToRegister[];
      payouts: PayoutSummary[];
    }
  | {
      answered: false;
      reason: "unreachable" | "not_added";
      message: string;
      networks: Network[];
    };

export interface MarkedRead {
  unread: number;
}

export interface Registered {
  clan_name: string;
  threshold: number;
  signers: number;
}

export interface ReviewLine extends CheckedAddress {
  name: string;
  approved_sats: number;
  received_sats: number;
}

export interface Review {
  clan_id: string;
  clan_name: string;
  kind: PayoutKind;
  generation: number;
  txid: string;
  lines: ReviewLine[];
  fee_sats: number;
  fee_paid_by: "clan" | "recipients" | string;
  total_sats: number;
  network: Network;
  large: boolean;
  replaces: string[];
  already_signed: boolean;
  destination: string | null;
}

export type PayoutStep =
  | { step: "wallet"; payout: PayoutSummary; wallets: WalletToRegister[] }
  | {
      step: "address";
      payout: PayoutSummary;
      line: number;
      name: string;
      fixed_start: string;
      characters: number;
    }
  | { step: "stopped"; payout: PayoutSummary; message: string }
  | { step: "review"; payout: PayoutSummary; review: Review; unread_alarms: number };

export interface Confirmed {
  confirmed: true;
}

export interface Approved {
  approved: true;
  complete: boolean;
  signatures: { count: number | null; required: number | null };
}

/** Each command, its arguments and its result. */
export interface Commands {
  status: [Record<string, never>, Status];
  create_key: [{ passphrase: string }, CreatedKey];
  restore_key: [{ words: string; passphrase: string }, RestoredKey];
  check_passphrase: [{ passphrase: string }, Ok];
  check_words: [
    { passphrase: string; answers: Record<string, string> },
    { matches: boolean; wrong: number[] },
  ];
  connect: [{ url?: string }, Connected];
  admin_lines: [Record<string, never>, AdminLines];
  records: [Record<string, never>, Records];
  clans: [Record<string, never>, Clan[]];
  funding_address: [{ clan_id: string }, FundingAddress];
  overview: [Record<string, never>, Overview];
  alarms: [{ recent?: boolean }, Alarm[]];
  mark_alarms_read: [{ newest: string }, MarkedRead];
  register_wallet: [{ clan_id: string; generation: number; code: string }, Registered];
  open_payout: [{ payout_id: string }, PayoutStep];
  confirm_address: [{ payout_id: string; line: number; characters: string }, Confirmed];
  approve: [
    {
      payout_id: string;
      passphrase: string;
      shown: { txid: string; total_sats: number };
      typed_total?: string;
    },
    Approved,
  ];
}

export type Command = keyof Commands;
