import { useCallback, useEffect, useState } from "react";
import { CheckCircle, WarningOctagon, Warning } from "@phosphor-icons/react";
import { call, sentence } from "./core";
import type { Alarm } from "./types";
import { useApp } from "./state";
import { Busy, Notice, PageHeading, Problem, plural, useFocusHeading, when } from "./ui";

const titles: Record<string, string> = {
  unapproved_spend: "Money left a clan wallet without going through Clans",
  wallet_code_mismatch: "A phone saw a different wallet code",
  invalid_signature: "A signature didn't match the payment",
  address_mismatch: "A stored address doesn't match the clan wallet",
  recovery_path_open: "A coin reached the recovery wait",
  receipt_reorg: "A payment the clan counted has disappeared",
  payout_reorg: "A confirmed payout has disappeared",
  payout_accounting: "A payout couldn't be booked",
  sweep_blocked: "A refresh or move couldn't be built",
};
const serious = new Set(["unapproved_spend", "wallet_code_mismatch", "address_mismatch"]);

function AlarmCard({ alarm }: { alarm: Alarm }) {
  const detail = Object.entries(alarm.detail || {});
  const Icon = serious.has(alarm.kind) ? WarningOctagon : Warning;
  return (
    <li className={`alarm-card ${serious.has(alarm.kind) ? "alarm-serious" : ""}`}>
      <Icon size={26} weight="fill" aria-hidden />
      <div>
        <p className="alarm-meta">
          {alarm.clan_name || (alarm.clan_id ? `Clan ${alarm.clan_id}` : "All clans")}
          {alarm.generation ? ` · wallet ${alarm.generation}` : ""} · {when(alarm.created_at)}
        </p>
        <h3>{titles[alarm.kind] || alarm.kind}</h3>
        {alarm.message && <p>{sentence(alarm.message)}</p>}
        {alarm.kind === "unapproved_spend" && (
          <div className="alarm-explain">
            <p>
              Someone may hold enough of that clan's keys.{" "}
              <strong>
                Don't approve anything for that clan until the team has found out what happened.
              </strong>
            </p>
          </div>
        )}
        {(detail.length > 0 || !titles[alarm.kind]) && (
          <details className="details">
            <summary>Details for the team</summary>
            <dl className="detail-list">
              <dt>Kind</dt>
              <dd>{alarm.kind}</dd>
              {detail.map(([key, value]) => (
                <div key={key} className="detail-row">
                  <dt>{key}</dt>
                  <dd>{typeof value === "string" ? value : JSON.stringify(value)}</dd>
                </div>
              ))}
            </dl>
          </details>
        )}
      </div>
    </li>
  );
}

export function Alarms() {
  const app = useApp();
  const [view, setView] = useState<"new" | "recent">("new");
  const [alarms, setAlarms] = useState<Alarm[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);
  const [marking, setMarking] = useState(false);
  const [note, setNote] = useState("");
  useFocusHeading("alarms");

  const load = useCallback(
    async (which: "new" | "recent") => {
      setLoading(true);
      setError(null);
      try {
        const found = await call("alarms", which === "recent" ? { recent: true } : {});
        // Newest first, the way people read a list of events.
        setAlarms([...found].sort((a, b) => (a.created_at < b.created_at ? 1 : -1)));
        if (which === "new") app.setUnread(found.length);
      } catch (reason) {
        setError(reason);
        setAlarms(null);
      } finally {
        setLoading(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  useEffect(() => {
    void load(view);
  }, [view, load]);

  async function markRead() {
    if (!alarms?.length) return;
    // The newest one shown, compared as text the way the core compares it.
    const newest = alarms.reduce((max, alarm) => (alarm.created_at > max ? alarm.created_at : max), "");
    setMarking(true);
    setError(null);
    try {
      const { unread } = await call("mark_alarms_read", { newest });
      app.setUnread(unread);
      app.changed();
      if (unread > 0) {
        setNote("More alarms came in while you were reading. Read these too.");
        await load("new");
      } else {
        setNote("Marked as read on this laptop. You can approve payouts again.");
        setAlarms([]);
      }
    } catch (reason) {
      setError(reason);
    } finally {
      setMarking(false);
    }
  }

  return (
    <div className="screen">
      <PageHeading eyebrow="Alarms" title={view === "new" ? "New alarms" : "Recent alarms"}>
        <div className="segmented" role="group" aria-label="Which alarms">
          <button
            className={view === "new" ? "active" : ""}
            aria-pressed={view === "new"}
            onClick={() => {
              setNote("");
              setView("new");
            }}
          >
            New
          </button>
          <button
            className={view === "recent" ? "active" : ""}
            aria-pressed={view === "recent"}
            onClick={() => {
              setNote("");
              setView("recent");
            }}
          >
            Recent
          </button>
        </div>
      </PageHeading>

      {note && <Notice tone={note.startsWith("More") ? "warning" : "good"}><p>{note}</p></Notice>}
      {error !== null && <Problem error={error} />}
      {loading && !alarms && <p className="quiet-line">Asking Clans for alarms…</p>}

      {alarms && view === "new" && alarms.length > 0 && (
        <p className="lead">
          {plural(alarms.length, "new alarm")}. Read each one. Payouts can't be approved until
          they're marked as read on this laptop.
        </p>
      )}
      {alarms && view === "recent" && (
        <p className="lead">The latest alarms about every clan's wallets, read or not.</p>
      )}

      {alarms && alarms.length > 0 && (
        <ul className="alarm-list">
          {alarms.map((alarm, index) => (
            <AlarmCard key={`${alarm.created_at}-${alarm.kind}-${index}`} alarm={alarm} />
          ))}
        </ul>
      )}

      {alarms && alarms.length === 0 && !note && (
        <section className="all-clear">
          <CheckCircle size={44} aria-hidden />
          <h2>{view === "new" ? "No new alarms." : "No alarms yet."}</h2>
          <p>Clans tells this laptop if something unusual happens in a clan wallet.</p>
        </section>
      )}

      {alarms && view === "new" && alarms.length > 0 && (
        <div className="actions actions-end sticky-actions">
          <button className="primary-button" onClick={() => void markRead()} disabled={marking}>
            <Busy busy={marking}>I've read these</Busy>
          </button>
        </div>
      )}
    </div>
  );
}
