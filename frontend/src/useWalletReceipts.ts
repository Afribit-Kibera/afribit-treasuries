import { useEffect, useRef, useState } from "react";
import {
  getWalletReceipts,
  safeSats,
  type AddressPurpose,
  type WalletReceipt,
} from "./wallet-api";
import { walletMessage } from "./wallet-trust";
import { communityName } from "./community";

const optionalCount = (value: unknown) =>
  value === null ||
  value === undefined ||
  (typeof value === "number" && Number.isSafeInteger(value) && value >= 0);

/** Only payments for the address already rebuilt on this phone may affect this screen. */
export function checkedReceipts(
  rows: WalletReceipt[],
  address: string,
  purpose: AddressPurpose,
  grantId?: string,
) {
  const unique = new Map<string, WalletReceipt>();
  for (const row of rows) {
    if (
      row.address !== address ||
      row.purpose !== purpose ||
      row.grant_id !== (grantId || null) ||
      !Number.isInteger(row.vout) ||
      row.vout < 0 ||
      !/^[a-f0-9]{64}$/.test(row.txid) ||
      row.id !== `${row.txid}:${row.vout}` ||
      !Number.isSafeInteger(row.confirmations) ||
      row.confirmations < 0 ||
      !["pending", "confirmed", "dropped"].includes(row.status) ||
      safeSats(row.amount_sats) <= 0n ||
      (row.status === "confirmed" && row.confirmations < 3) ||
      // Confirmed but not counted yet only while it waits for a KES rate.
      (row.status === "pending" &&
        row.confirmations >= 3 &&
        row.credit_note !== "waiting_for_rate") ||
      (row.credit_note != null && row.credit_note !== "waiting_for_rate") ||
      !optionalCount(row.kes_credited_minor) ||
      !optionalCount(row.kes_owed_after_minor) ||
      (row.kes_per_btc != null && !/^\d{1,15}(\.\d{1,20})?$/.test(row.kes_per_btc))
    )
      throw Error(
        `These payment details do not match the address this phone checked. Please try again or contact ${communityName()}.`,
      );
    const old = unique.get(row.id);
    if (old && JSON.stringify(old) !== JSON.stringify(row))
      throw Error(
        `The same payment has conflicting details. Please contact ${communityName()}.`,
      );
    unique.set(row.id, row);
  }
  return [...unique.values()];
}
export function useWalletReceipts({
  clanId,
  address,
  purpose,
  grantId,
  amount,
  onConfirmed,
  interval = 30000,
}: {
  clanId: string;
  address: string;
  purpose: AddressPurpose;
  grantId?: string;
  amount: bigint;
  onConfirmed?: () => Promise<unknown>;
  /** How often to check while waiting, in milliseconds. */
  interval?: number;
}) {
  const [payments, setPayments] = useState<WalletReceipt[]>([]),
    [received, setReceived] = useState(0n),
    [checking, setChecking] = useState(false),
    [error, setError] = useState(""),
    [refresh, setRefresh] = useState(0);
  const known = useRef<Map<string, WalletReceipt> | null>(null),
    history = useRef(new Set<string>()),
    notified = useRef(new Set<string>()),
    scope = useRef(""),
    onConfirmedRef = useRef(onConfirmed);
  onConfirmedRef.current = onConfirmed;
  const identity = `${clanId}:${address}:${purpose}:${grantId || ""}`;
  useEffect(() => {
    if (scope.current !== identity) {
      scope.current = identity;
      known.current = null;
      history.current = new Set();
      notified.current = new Set();
    }
    let alive = true,
      running = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    if (known.current === null) {
      setPayments([]);
      setReceived(0n);
    }
    setError("");
    if (!address) return;
    async function poll() {
      if (!alive || running) return;
      clearTimeout(timer);
      running = true;
      setChecking(true);
      let again = true;
      try {
        const rows = checkedReceipts(
          await getWalletReceipts(clanId, address),
          address,
          purpose,
          grantId,
        );
        if (!alive) return;
        if (known.current === null)
          history.current = new Set(
            rows.filter((r) => r.status === "confirmed").map((r) => r.id),
          );
        known.current = new Map(rows.map((r) => [r.id, r]));
        const confirmed = rows.filter(
          (r) => r.status === "confirmed" && !history.current.has(r.id),
        );
        const total = confirmed.reduce(
          (sum, r) => sum + safeSats(r.amount_sats),
          0n,
        );
        setPayments(rows);
        setReceived(total);
        setError("");
        const fresh = confirmed.filter((r) => !notified.current.has(r.id));
        if (fresh.length) {
          await onConfirmedRef.current?.();
          if (!alive) return;
          fresh.forEach((r) => notified.current.add(r.id));
        }
        again = rows.some((r) => r.status === "pending") || total < amount;
      } catch (e) {
        if (alive) setError(walletMessage(e));
      } finally {
        running = false;
        if (alive) {
          setChecking(false);
          if (again) timer = setTimeout(() => void poll(), interval);
        }
      }
    }
    const resume = () => {
      if (document.visibilityState === "visible") void poll();
    };
    void poll();
    window.addEventListener("focus", resume);
    document.addEventListener("visibilitychange", resume);
    return () => {
      alive = false;
      clearTimeout(timer);
      window.removeEventListener("focus", resume);
      document.removeEventListener("visibilitychange", resume);
    };
  }, [identity, refresh, interval]);
  return {
    payments,
    /** Payments that weren't already counted when this screen opened. */
    fresh: payments.filter((r) => !history.current.has(r.id)),
    received,
    checking,
    error,
    refresh: () => setRefresh((n) => n + 1),
  };
}
