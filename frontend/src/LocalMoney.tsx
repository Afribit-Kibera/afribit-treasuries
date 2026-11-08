import { useEffect, useState } from "react";
import { api } from "./live-api";

export type Rate = {
  currency: string;
  per_btc: string;
  published_at: number;
  valid_until: number;
  source: string;
};
export function useRate(currency: string) {
  const [rate, setRate] = useState<Rate | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const next = await api<Rate>(`/rates/${currency}`);
        if (active) {
          setRate(next);
          setUnavailable(false);
        }
      } catch {
        if (active) {
          setRate(null);
          setUnavailable(true);
        }
      }
    };
    setRate(null);
    setUnavailable(false);
    void load();
    const timer = setInterval(() => void load(), 60_000);
    const expiry = setInterval(
      () =>
        setRate((old) =>
          old && old.valid_until * 1000 > Date.now() ? old : null,
        ),
      1000,
    );
    return () => {
      active = false;
      clearInterval(timer);
      clearInterval(expiry);
    };
  }, [currency]);
  return {
    rate:
      rate?.currency === currency && rate.valid_until * 1000 > Date.now()
        ? rate
        : null,
    unavailable,
  };
}

export function localMoney(
  msat: string,
  rate: Rate,
  compact = false,
  locale = navigator.language || "en-KE",
) {
  // Integer display conversion; available money is rounded down to the cent.
  const [whole, fraction = ""] = rate.per_btc.split(".");
  const scale = 10n ** BigInt(fraction.length);
  const perBtc = BigInt(whole + fraction);
  const minor = (BigInt(msat) * perBtc * 100n) / (100_000_000_000n * scale);
  const integer = new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(minor / 100n);
  const cents = (minor % 100n).toString().padStart(2, "0");
  const shown = compact ? cents.replace(/0+$/, "") : cents;
  const separator = new Intl.NumberFormat(locale).formatToParts(1.1).find(part => part.type === "decimal")?.value || ".";
  const digits = new Intl.NumberFormat(locale, { useGrouping: false });
  const localized = [...shown].map(digit => digits.format(Number(digit))).join("");
  return `${rate.currency} ${integer}${shown ? separator + localized : ""}`;
}
