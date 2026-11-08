// Imported only from the development preview. All records are synthetic test-network data.
import { entropyToMnemonic } from "@scure/bip39";
import { wordlist } from "@scure/bip39/wordlists/english.js";
import { signerFromWords } from "./vault/keys";
import { keyExpression, clanOutput, walletCode } from "./vault/policy";
import { toClanPolicy, type WalletStatus, type WalletView } from "./wallet-api";
export { fixturePayout, tamperedPayout } from "./wallet-payout-fixture";
export function fixtureWords(index: number) {
  return entropyToMnemonic(new Uint8Array(16).fill(index), wordlist);
}
export function walletFixture(status: WalletStatus = "active"): WalletView {
  const keys = [1, 2, 3, 4].map((i) =>
    keyExpression(signerFromWords(fixtureWords(i), "signet").info),
  );
  const ready = !["not_started", "collecting_keys"].includes(status);
  const policy = {
    network: "signet" as const,
    oversight: [keys[0]],
    signers: keys.slice(1).sort(),
    recovery_threshold: 2,
    recovery_blocks: 26280,
  };
  return {
    next: null,
    earlier: [],
    started_by: null,
    start_reason: null,
    enabled: true,
    status,
    generation: status === "not_started" ? null : 1,
    network: "signet",
    signer_count: 3,
    threshold: 2,
    recovery_threshold: 2,
    recovery_blocks: 26280,
    recovery_days: 182,
    oversight_keys: [keys[0]],
    signers: ["Amina", "Juma", "Grace"].map((display_name, i) => ({
      user_id: `fixture-${i}`,
      display_name,
      key_registered: status !== "not_started" && (ready || i === 0),
      fingerprint: null,
      confirmed: status === "active",
    })),
    me: {
      is_signer: true,
      key: status === "not_started" ? null : keys[1],
      confirmed: status === "active",
    },
    policy: ready ? policy : null,
    wallet_code: ready ? walletCode(toClanPolicy(policy)) : null,
    activated_at: status === "active" ? "2026-11-04T09:00:00+03:00" : null,
  };
}
export function addressFixture() {
  const view = walletFixture();
  return {
    address: clanOutput(toClanPolicy(view.policy!), "external", 0).address,
    keychain: "external" as const,
    index: 0,
    purpose: "contribution" as const,
    grant_id: null,
  };
}
export function nextWalletFixture() {
  const current = walletFixture("active");
  const upcoming = walletFixture("collecting_keys");
  return {
    ...current,
    next: {
      ...upcoming,
      generation: 2,
      started_by: "Grace",
      start_reason: "stolen_phone" as const,
    },
  };
}
export function movedWalletFixture() {
  const old = walletFixture("active");
  const current = walletFixture("active");
  current.generation = 2;
  const newKey = keyExpression(signerFromWords(fixtureWords(5), "signet").info);
  const replacedKey = keyExpression(signerFromWords(fixtureWords(4), "signet").info);
  current.policy!.signers = current
    .policy!.signers.filter((k) => k !== replacedKey)
    .concat(newKey)
    .sort();
  current.wallet_code = walletCode(toClanPolicy(current.policy!));
  current.earlier = [
    {
      generation: 1,
      wallet_code: old.wallet_code!,
      retired_at: "2026-11-05T12:00:00Z",
      balance_sats: 100000,
    },
  ];
  return current;
}
