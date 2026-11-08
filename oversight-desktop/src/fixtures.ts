// Dev only: answers core() from fixed data with the service's shapes, to see every screen
// without a Clans server. core.ts loads this only when import.meta.env.DEV and the URL has
// ?fixtures, so it never reaches the production build.
//
//   ?fixtures            work waiting: alarms, a wallet to register, five payouts
//   ?fixtures=clear      nothing waiting
//   ?fixtures=new        first run, no key
//   ?fixtures=connect    a key but not connected
//   ?fixtures=not_added  connected, but Clans doesn't know this laptop yet
//   ?fixtures=unreachable
//
// Passphrase: "correct horse battery staple". Wallet codes: Mama Mboga m4wd8n3p, Toi Market
// (wallet 2) r9tx2kq6. Juma reads 7xk2m9 then 4hq8zt.

import type {
  Alarm,
  Clan,
  Commands,
  PayoutStep,
  PayoutSummary,
  Review,
  ReviewLine,
  WalletToRegister,
} from "./types";

if (!import.meta.env.DEV) throw new Error("Fixtures are for dev only");

const PASSPHRASE = "correct horse battery staple";
const scenario = new URLSearchParams(location.search).get("fixtures") || "work";

class Failure {
  constructor(
    readonly error: string,
    readonly code: "check" | "refused" | "internal" = "check",
    readonly reason?: string,
  ) {}
}

const WORDS = "orbit sunny maple ankle lizard velvet harbor glory cabin rescue tiny pledge".split(" ");

function checked(name: string, address: string, approved: number, received: number): ReviewLine {
  const start = address.slice(0, address.lastIndexOf("1") + 2);
  return {
    name,
    address,
    fixed_start: start,
    check_start: address.slice(start.length, start.length + 6),
    check_end: address.slice(-6),
    approved_sats: approved,
    received_sats: received,
  };
}

const JUMA = "tb1q7xk2m9v3d5w8pzr0n4y6c2hf8g9j3l5k4hq8zt";
const ACHIENG = "tb1qa8n3f6wq2x7r9kd4m5zp0c8h3y6t2l9vj7e4su";
const OTIENO = "tb1qz5r8k2m6p9x3w7d4f0n8h2c6y5t3q9l7g4a2wn";
const WANJIRU = "tb1qk9d2w7m4x8r3n6p5z0f2h7c3y9t6q4l8s5e3rm";
const CLAN_CHANGE = "tb1qmuxsr0h45ng4p2c7vtwlfh3k6nj0yd9dp8ac5x2qw8yz3e7r6ta3xqhvm";

const state = {
  hasKey: scenario !== "new",
  connected: !["new", "connect"].includes(scenario),
  unread: scenario === "work",
  clans: [
    { clan_id: "c-1", clan_name: "Kibera Real Sats", generation: 1, wallet_code: "k7vq9x2m", network: "signet", threshold: 2, signers: 3 },
    { clan_id: "c-3", clan_name: "Toi Market Traders", generation: 1, wallet_code: "h3cs6uaf", network: "signet", threshold: 2, signers: 4 },
  ] as Clan[],
  toRegister: (scenario === "work"
    ? [
        { clan_id: "c-2", clan_name: "Mama Mboga Group", generation: 1 },
        { clan_id: "c-3", clan_name: "Toi Market Traders", generation: 2 },
      ]
    : []) as WalletToRegister[],
  confirmed: new Set<string>([ACHIENG, OTIENO, WANJIRU]),
  approvals: [
    { signed_at: "2026-11-04T09:12:00+00:00", clan_id: "c-1", clan_name: "Kibera Real Sats", kind: "grant", total_sats: 4_000, fee_sats: 212, txid: "9c1e0a7b44d2f8a1b6e3c5d7f9a0b2c4d6e8f0a1b3c5d7e9f1a3b5c7d9e1f3a5" },
  ],
  payouts: (scenario === "work"
    ? ["p-101", "p-102", "p-103", "p-104", "p-105"]
    : []) as string[],
};

const summaries: Record<string, PayoutSummary> = {
  "p-101": { id: "p-101", clan_id: "c-1", clan_name: "Kibera Real Sats", kind: "grant", created_at: "2026-11-06T07:40:00+00:00", beneficiaries: ["Juma"], approved_sats: 2_530 },
  "p-102": { id: "p-102", clan_id: "c-1", clan_name: "Kibera Real Sats", kind: "grant", created_at: "2026-11-06T08:05:00+00:00", beneficiaries: ["Achieng", "Otieno"], approved_sats: 150_000 },
  "p-103": { id: "p-103", clan_id: "c-2", clan_name: "Mama Mboga Group", kind: "grant", created_at: "2026-11-06T08:30:00+00:00", beneficiaries: ["Wanjiru"], approved_sats: 6_000 },
  "p-104": { id: "p-104", clan_id: "c-3", clan_name: "Toi Market Traders", kind: "move", created_at: "2026-11-06T09:10:00+00:00", beneficiaries: [], approved_sats: 0 },
  "p-105": { id: "p-105", clan_id: "c-1", clan_name: "Kibera Real Sats", kind: "grant", created_at: "2026-11-06T09:20:00+00:00", beneficiaries: ["Baraka"], approved_sats: 3_100 },
};

const reviews: Record<string, Omit<Review, "network">> = {
  "p-101": {
    clan_id: "c-1", clan_name: "Kibera Real Sats", kind: "grant", generation: 1,
    txid: "4b7f2c9e1a3d5f7b9c1e3a5d7f9b1c3e5a7d9f1b3c5e7a9d1f3b5c7e9a1d3f5b",
    lines: [checked("Juma", JUMA, 2_530, 2_302)],
    fee_sats: 228, fee_paid_by: "recipients", total_sats: 2_530, large: false,
    replaces: [], already_signed: false, destination: null,
  },
  "p-102": {
    clan_id: "c-1", clan_name: "Kibera Real Sats", kind: "grant", generation: 1,
    txid: "e2a4c6e8f0b2d4f6a8c0e2b4d6f8a0c2e4b6d8f0a2c4e6b8d0f2a4c6e8b0d2f4",
    lines: [checked("Achieng", ACHIENG, 100_000, 100_000), checked("Otieno", OTIENO, 50_000, 50_000)],
    fee_sats: 341, fee_paid_by: "clan", total_sats: 150_000, large: true,
    replaces: ["9c1e0a7b44d2f8a1b6e3c5d7f9a0b2c4d6e8f0a1b3c5d7e9f1a3b5c7d9e1f3a5"], already_signed: false, destination: null,
  },
  "p-103": {
    clan_id: "c-2", clan_name: "Mama Mboga Group", kind: "grant", generation: 1,
    txid: "1f3e5d7c9b1a3f5e7d9c1b3a5f7e9d1c3b5a7f9e1d3c5b7a9f1e3d5c7b9a1f3e",
    lines: [checked("Wanjiru", WANJIRU, 6_000, 6_000)],
    fee_sats: 198, fee_paid_by: "clan", total_sats: 6_000, large: false,
    replaces: [], already_signed: true, destination: null,
  },
  "p-104": {
    clan_id: "c-3", clan_name: "Toi Market Traders", kind: "move", generation: 1,
    txid: "7a9c1e3f5b7d9a1c3e5f7b9d1a3c5e7f9b1d3a5c7e9f1b3d5a7c9e1f3b5d7a9c",
    lines: [checked("Move to the clan's new wallet (2)", CLAN_CHANGE, 84_500, 84_500)],
    fee_sats: 1_420, fee_paid_by: "clan", total_sats: 84_500, large: false,
    replaces: [], already_signed: false, destination: CLAN_CHANGE,
  },
};

const alarmList: Alarm[] = [
  {
    created_at: "2026-11-06T06:58:12.204+00:00", kind: "unapproved_spend",
    message: "Money left the clan wallet without an approved payout. Afribit is looking into it. Don't approve anything until Afribit has explained it.",
    clan_id: "c-3", clan_name: "Toi Market Traders", generation: 1,
    detail: { txid: "5d2c8e1f4a7b0c3d6e9f2a5b8c1d4e7f0a3b6c9d2e5f8a1b4c7d0e3f6a9b2c5d" },
  },
  {
    created_at: "2026-11-05T18:21:40.000+00:00", kind: "sweep_blocked",
    message: "A refresh or move couldn't be built, usually because network fees are above the limit.",
    clan_id: "c-1", clan_name: "Kibera Real Sats", generation: 1, detail: {},
  },
];
const olderAlarm: Alarm = {
  created_at: "2026-10-30T11:02:00.000+00:00", kind: "wallet_code_mismatch",
  message: "A signatory's phone computed a different wallet code. Don't use this wallet until Afribit has checked it.",
  clan_id: "c-1", clan_name: "Kibera Real Sats", generation: 1, detail: { phone_code: "k7vq9x2n" },
};

const walletCodes: Record<string, string> = { "c-2:1": "m4wd8n3p", "c-3:2": "r9tx2kq6" };
const policies: Record<string, { threshold: number; signers: number }> = {
  "c-2": { threshold: 3, signers: 5 },
  "c-3": { threshold: 2, signers: 4 },
};

function pause(ms: number) {
  return new Promise((done) => setTimeout(done, ms));
}

function needsServer() {
  if (!state.connected) throw new Failure("This laptop isn't connected to Clans yet. Run connect first");
  if (scenario === "not_added") throw new Failure("Clans refused this (401): Not authenticated");
  if (scenario === "unreachable") throw new Failure("Couldn't reach Clans (ConnectError). Try again");
}

function registered(clanId: string, generation: number) {
  return !state.toRegister.some((item) => item.clan_id === clanId && item.generation === generation);
}

function openPayout(id: string): PayoutStep {
  if (!state.payouts.includes(id))
    throw new Failure("This payout isn't waiting for you any more. It may have been approved on another laptop or replaced", "check", "payout_gone");
  const payout = summaries[id];
  const needed = id === "p-103" ? [["c-2", 1]] : id === "p-104" ? [["c-3", 2]] : [];
  const missing = needed
    .filter(([clan, generation]) => !registered(clan as string, generation as number))
    .map(([clan, generation]) => state.toRegister.find((w) => w.clan_id === clan && w.generation === generation)!);
  if (missing.length) return { step: "wallet", payout, wallets: missing };
  if (id === "p-101" && !state.confirmed.has(JUMA))
    return { step: "address", payout, line: 0, name: "Juma", fixed_start: "tb1q", characters: 12 };
  if (id === "p-105")
    return { step: "stopped", payout, message: "The network fee is 12,400 sats, above this laptop's limit of 5,000 sats" };
  return { step: "review", payout, review: { ...reviews[id], network: "signet" }, unread_alarms: state.unread ? alarmList.length : 0 };
}

type Handler = (args: Record<string, unknown>) => unknown | Promise<unknown>;

const handlers: { [C in keyof Commands]: Handler } = {
  status: () => ({
    protocol: 1,
    has_key: state.hasKey,
    connected: state.connected,
    server: state.connected ? "https://clans.afribit.africa" : null,
    default_server: "https://clans.afribit.africa",
    home: "C:\\Users\\oversight\\AppData\\Local\\AfribitOversight",
    has_mainnet_key: state.hasKey,
    registered_wallets: state.clans.length,
  }),
  create_key: async ({ passphrase }) => {
    await pause(900);
    if (String(passphrase).length < 12) throw new Failure("Use a passphrase of at least 12 characters");
    state.hasKey = true;
    return { words: WORDS, public_key: "tpubD6NzVbkrYhZ4X…" };
  },
  restore_key: async ({ words }) => {
    await pause(900);
    if (String(words).split(" ").length !== 12) throw new Failure("These backup words are not valid", "check", "bad_words");
    state.hasKey = true;
    return { public_key: "tpubD6NzVbkrYhZ4X…" };
  },
  check_words: async ({ passphrase, answers }) => {
    await pause(300);
    if (passphrase !== PASSPHRASE) throw new Failure("Wrong passphrase", "check", "wrong_passphrase");
    const typed = Object.entries(answers as Record<string, string>);
    const wrong = typed
      .filter(([n, word]) => word.trim().toLowerCase() !== WORDS[Number(n) - 1])
      .map(([n]) => Number(n))
      .sort((a, b) => a - b);
    return { matches: wrong.length === 0, wrong };
  },
  check_passphrase: async ({ passphrase }) => {
    await pause(900);
    if (passphrase !== PASSPHRASE) throw new Failure("Wrong passphrase", "check", "wrong_passphrase");
    return { ok: true };
  },
  connect: () => {
    state.connected = true;
    return { connection_line: "3f7a…", admin_text: adminText() };
  },
  admin_lines: () => ({ text: adminText() }),
  records: () => ({
    addresses: [...state.confirmed].map((address, index) => ({
      name: ["Achieng", "Otieno", "Wanjiru", "Juma"][index] || "Beneficiary",
      address,
      confirmed_at: "2026-11-02T10:15:00+00:00",
    })),
    approvals: state.approvals,
    settings: { max_fee_sats: 5_000, max_sweep_fee_sats: 10_000, large_payout_sats: 100_000 },
    register_file: "C:\\Users\\oversight\\AppData\\Local\\AfribitOversight\\register.json",
  }),
  clans: () => state.clans,
  funding_address: ({ clan_id }) => {
    const address = clan_id === "c-1" ? "tb1qf8x2k7m3w9d5r4n6p0z2h8c5y3t7q6l9s4e2vk" : "tb1q4n7d2m9x5w3r8k6p0f2h4c7y9t5q3l6s8e2gxd";
    const start = "tb1q";
    return { address, fixed_start: start, check_start: address.slice(4, 10), check_end: address.slice(-6) };
  },
  overview: async () => {
    await pause(350);
    try {
      needsServer();
    } catch (failure) {
      const text = (failure as Failure).error;
      const reason = text.includes("(401)") ? "not_added" : "unreachable";
      return { answered: false, reason, message: text, networks: state.clans.map((c) => c.network) };
    }
    return {
      answered: true,
      community: "Kibera Savers",
      networks: [...new Set(state.clans.map((c) => c.network))],
      alarms: state.unread ? alarmList : [],
      wallets_to_register: state.toRegister,
      payouts: state.payouts.map((id) => summaries[id]),
    };
  },
  alarms: ({ recent }) => {
    needsServer();
    if (recent) return [...alarmList, olderAlarm];
    return state.unread ? alarmList : [];
  },
  mark_alarms_read: () => {
    needsServer();
    state.unread = false;
    return { unread: 0 };
  },
  register_wallet: async ({ clan_id, generation, code }) => {
    await pause(400);
    needsServer();
    const key = `${clan_id}:${generation}`;
    const wallet = state.toRegister.find((w) => w.clan_id === clan_id && w.generation === generation);
    if (!wallet) throw new Failure("This wallet is already registered, or Clans no longer lists it");
    if (String(code).replace(/[\s-]/g, "").toLowerCase() !== walletCodes[key])
      throw new Failure("The wallet code doesn't match the signatory's phone. Don't approve anything for this clan, and tell the clan and Afribit", "check", "code_mismatch");
    state.toRegister = state.toRegister.filter((w) => w !== wallet);
    const policy = policies[String(clan_id)];
    const others = state.clans.filter((c) => c.clan_id !== clan_id);
    state.clans = [...others, { clan_id: String(clan_id), clan_name: wallet.clan_name, generation: Number(generation), wallet_code: walletCodes[key], network: "signet", ...policy }];
    return { clan_name: wallet.clan_name, ...policy };
  },
  open_payout: async ({ payout_id }) => {
    await pause(450);
    needsServer();
    return openPayout(String(payout_id));
  },
  confirm_address: async ({ characters }) => {
    await pause(300);
    if (String(characters) !== "7xk2m94hq8zt")
      throw new Failure("The characters the beneficiary read don't match. Don't use this address. Ask them to check their wallet, and tell Afribit if it still differs", "check", "address_mismatch");
    state.confirmed.add(JUMA);
    return { confirmed: true };
  },
  approve: async ({ payout_id, passphrase, shown, typed_total }) => {
    await pause(1100);
    needsServer();
    if (state.unread) throw new Failure("There are new alarms. Read them before approving", "check", "alarms_unread");
    const step = openPayout(String(payout_id));
    if (step.step !== "review") throw new Failure("Open the payout first", "refused");
    const { txid, total_sats } = shown as { txid: string; total_sats: number };
    if (txid !== step.review.txid || total_sats !== step.review.total_sats)
      throw new Failure("This payout changed since you opened it. Nothing was signed. Open it again and check it from the start", "check", "payout_changed");
    if (step.review.large && String(typed_total || "").replace(/[,\s]/g, "") !== String(step.review.total_sats))
      throw new Failure("That isn't the total. Nothing was signed", "check", "wrong_total");
    if (passphrase !== PASSPHRASE) throw new Failure("Wrong passphrase", "check", "wrong_passphrase");
    state.payouts = state.payouts.filter((id) => id !== payout_id);
    state.approvals = [
      { signed_at: new Date().toISOString(), clan_id: step.review.clan_id, clan_name: step.review.clan_name, kind: step.review.kind, total_sats: step.review.total_sats, fee_sats: step.review.fee_sats, txid },
      ...state.approvals,
    ];
    return { approved: true, complete: true, signatures: { count: 3, required: 3 } };
  },
};

function adminText() {
  return [
    "Oversight laptop: OVERSIGHT-01",
    "Oversight public key: tpubDC8msFGeGuwnKG9Upg7DM2b4DaRqg3CUZa5g8v2SRQ6K4NSkxUgd7HsL2XVWbVaXtRkv3ZYvu",
    "Mainnet oversight public key: xpub6CUGRUonZSQ4TWtTMmzXdrXDtypWKiKrhko4egpiMZbpiaQL2jkwSB1icqYh2cfDfVxdx4df189oLKnC5fSwqPfgyP3hooxujYzAu3fDVmz",
    state.connected ? "Connection line: 3f7a9c2e5b8d1f4a7c0e3b6d9f2a5c8e1b4d7f0a3c6e9b2d5f8a1c4e7b0d3f6a" : "",
    "These lines are safe to send. They hold no secret and can't approve anything.",
  ]
    .filter(Boolean)
    .join("\n") + "\n";
}

export async function answer(command: string, args: object): Promise<unknown> {
  const handler = handlers[command as keyof Commands];
  await pause(120);
  if (!handler) throw { error: "Unknown command", code: "refused" };
  try {
    // Copies, so the screens can't change the fixture state by accident.
    return structuredClone(await handler(args as Record<string, unknown>));
  } catch (failure) {
    if (failure instanceof Failure) throw { error: failure.error, code: failure.code, reason: failure.reason };
    throw { error: String(failure), code: "internal" };
  }
}
