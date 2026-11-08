import { useCallback, useEffect, useRef, useState } from "react";
import { getWallet, type WalletView } from "./wallet-api";
export function useClanWallet(id: string) {
  const [view, setView] = useState<WalletView | null>(null),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(true);
  const current = useRef(id);
  current.current = id;
  const sequence = useRef(0);
  const refresh = useCallback(async () => {
    if (!id) {
      setLoading(false);
      setView(null);
      setError("");
      return null;
    }
    const request = ++sequence.current;
    setLoading(true);
    setError("");
    try {
      const next = await getWallet(id);
      if (current.current === id && sequence.current === request) setView(next);
      return next;
    } catch (e) {
      if (current.current === id && sequence.current === request)
        setError((e as Error).message);
      return null;
    } finally {
      if (current.current === id && sequence.current === request)
        setLoading(false);
    }
  }, [id]);
  useEffect(() => {
    setView(null);
    void refresh();
    return () => {
      sequence.current++;
    };
  }, [refresh]);
  return { view, error, loading, refresh, setView };
}
