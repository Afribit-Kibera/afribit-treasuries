import { useCallback, useEffect, useState } from "react";
import { CircleNotch } from "@phosphor-icons/react";
import { call } from "./core";
import type { Status } from "./types";
import { Problem } from "./ui";
import { Setup } from "./Setup";
import { Shell } from "./Shell";

/** Start: no key → first-run setup; a key but no connection → the connect step; else Home. */
export default function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState<unknown>(null);
  const load = useCallback(async () => {
    setError(null);
    try {
      setStatus(await call("status"));
    } catch (reason) {
      setError(reason);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  if (error)
    return (
      <div className="start">
        <Problem error={error} />
        <button className="secondary-button" onClick={() => void load()}>
          Try again
        </button>
      </div>
    );
  if (!status)
    return (
      <div className="start" role="status">
        <CircleNotch className="spin" size={28} aria-hidden />
        <p>Opening Afribit Oversight…</p>
      </div>
    );
  if (!status.has_key || !status.connected)
    return <Setup status={status} onDone={() => void load()} />;
  return <Shell status={status} />;
}
