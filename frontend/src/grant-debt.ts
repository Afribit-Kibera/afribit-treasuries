import type { Grant } from "./live-api";
import type { Rate } from "./LocalMoney";

/** Grants asked for in KES are KES debts. Older grants, and sats requests, are in sats. */
export const isKesDebt = (grant: Grant) => grant.obligation_currency === "KES";

/** KES cents as members read money: KES 1,234.50. */
export function kesMinor(minor: number | bigint, locale = "en-KE") {
  const cents = BigInt(minor);
  const whole = new Intl.NumberFormat(locale).format(cents / 100n);
  return `KES ${whole}.${(cents % 100n).toString().padStart(2, "0")}`;
}

const sats = (value: number | bigint, locale = "en-KE") =>
  `${new Intl.NumberFormat(locale).format(value)} sats`;

/** What is still owed on a grant, in the debt's own currency. */
export function owedLabel(grant: Grant, locale?: string) {
  if (isKesDebt(grant)) return kesMinor(grant.outstanding_minor ?? 0, locale);
  return sats(BigInt(grant.outstanding_msat || "0") / 1000n, locale);
}

/** "about 12,345 sats at today's rate" for a KES debt, when the server had a rate. */
export function owedEstimate(grant: Grant, locale?: string) {
  const estimate = grant.outstanding_sats_estimate;
  if (!isKesDebt(grant) || estimate === null || estimate === undefined)
    return "";
  return `about ${sats(estimate, locale)} at today’s rate`;
}

/** KES cents typed by a member ("1500" or "1500.50"), or null. */
export function parseKes(value: string): bigint | null {
  const match = /^(\d{1,9})(?:\.(\d{1,2}))?$/.exec(value.trim());
  if (!match) return null;
  return BigInt(match[1]) * 100n + BigInt((match[2] || "").padEnd(2, "0"));
}

/** About how many sats KES cents buy at a rate, rounded up to a whole sat. */
export function satsForKes(minor: bigint, rate: Rate) {
  const [whole, fraction = ""] = rate.per_btc.split(".");
  const perBtc = BigInt(whole + fraction);
  const scale = 10n ** BigInt(fraction.length);
  if (perBtc <= 0n) return 0n;
  // minor / 100 KES ÷ (per_btc KES/BTC) × 100,000,000 sats/BTC
  const top = minor * 1_000_000n * scale;
  return (top + perBtc - 1n) / perBtc;
}
