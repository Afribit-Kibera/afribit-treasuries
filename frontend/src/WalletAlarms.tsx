import { useCallback, useEffect, useRef, useState } from "react";
import { WarningCircle } from "@phosphor-icons/react";
import { Sheet, Busy } from "./ui";
import { getWalletAlarms, type WalletAlarm, type WalletView } from "./wallet-api";
import { walletMessage } from "./wallet-trust";
import { communityName } from "./community";

const DAY_MS = 24 * 60 * 60 * 1000;
const fallback = () =>
  `Something unusual happened in the clan wallet. ${communityName()} is looking into it.`;

function time(alarm: WalletAlarm) {
  const raw = typeof alarm.created_at === "string" ? alarm.created_at : "";
  // The server sends UTC; read a time without a zone as UTC too.
  const at = Date.parse(
    /(Z|[+-]\d\d:?\d\d)$/i.test(raw) || !raw.includes("T") ? raw : raw + "Z",
  );
  return Number.isFinite(at) ? at : 0;
}
function alarmText(alarm: WalletAlarm) {
  return typeof alarm.message === "string" && alarm.message.trim()
    ? alarm.message
    : fallback();
}
/** The only detail members see: the code another signatory's phone computed. */
function phoneCode(alarm: WalletAlarm) {
  const code = alarm.detail?.phone_code;
  return alarm.kind === "wallet_code_mismatch" &&
    typeof code === "string" &&
    code.length <= 64
    ? code
    : "";
}
export function recentSpendAlarm(
  alarms: WalletAlarm[],
  generation: number | null,
  now = Date.now(),
) {
  return alarms.some(
    (a) =>
      a.kind === "unapproved_spend" &&
      generation !== null &&
      a.generation === generation &&
      now - time(a) <= 30 * DAY_MS,
  );
}
/** Loads the clan's alarms. Failures only set `error`; they never throw. */
export function useWalletAlarms(clanId: string, load = true) {
  const [alarms, setAlarms] = useState<WalletAlarm[] | null>(null),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(false);
  const alive = useRef(true);
  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const rows = await getWalletAlarms(clanId);
      if (!Array.isArray(rows)) throw Error("Could not load wallet alarms.");
      const clean = rows
        .filter((a) => a && typeof a === "object")
        .sort((a, b) => time(b) - time(a));
      if (alive.current) setAlarms(clean);
    } catch (e) {
      if (alive.current)
        setError(walletMessage(e) || "Could not load wallet alarms.");
    } finally {
      if (alive.current) setLoading(false);
    }
  }, [clanId]);
  useEffect(() => {
    alive.current = true;
    if (load) void refresh();
    return () => {
      alive.current = false;
    };
  }, [load, refresh]);
  return { alarms, error, loading, refresh };
}
function AlarmList({ clanId, view }: { clanId: string; view: WalletView }) {
  const { alarms, error, loading, refresh } = useWalletAlarms(clanId);
  const showGeneration =
    (view.generation ?? 0) > 1 ||
    new Set((alarms || []).map((a) => a.generation)).size > 1;
  if (!alarms && !error) return <p role="status">Loading wallet alarms…</p>;
  return (
    <div className="wallet-flow">
      {error && (
        <>
          <p role="alert">Could not load wallet alarms. {error}</p>
          <button
            className="secondary-button"
            disabled={loading}
            onClick={() => void refresh()}
          >
            <Busy busy={loading}>Try again</Busy>
          </button>
        </>
      )}
      {alarms && !alarms.length && (
        <p>
          No alarms. Clans tells every member here if something unusual happens
          in the clan wallet.
        </p>
      )}
      {alarms && !!alarms.length && (
        <ul className="wallet-waiting">
          {alarms.map((a, i) => {
            const at = time(a);
            const code = phoneCode(a);
            return (
              <li key={a.id || i}>
                <div>
                  <p>{alarmText(a)}</p>
                  {code && (
                    <p>
                      Wallet code on that phone: <strong>{code}</strong>.
                      Compare it with the code on your phone.
                    </p>
                  )}
                  <p className="fine-print">
                    {at
                      ? new Date(at).toLocaleString([], {
                          dateStyle: "medium",
                          timeStyle: "short",
                        })
                      : "Date unknown"}
                    {showGeneration && Number.isInteger(a.generation)
                      ? ` · wallet generation ${a.generation}`
                      : ""}
                  </p>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
/** Banner and alarm list for the wallet card. Shown to signatories and plain members. */
export function WalletAlarms({
  clanId,
  view,
}: {
  clanId: string;
  view: WalletView;
}) {
  const [open, setOpen] = useState(false);
  const recent =
    Number.isSafeInteger(view.alarms_recent) && view.alarms_recent! > 0
      ? view.alarms_recent!
      : 0;
  return (
    <>
      {recent > 0 ? (
        <button
          type="button"
          className="live-alert error"
          style={{ width: "100%", textAlign: "left" }}
          onClick={() => setOpen(true)}
        >
          <WarningCircle size={20} />
          <span>
            {recent} wallet {recent === 1 ? "alarm" : "alarms"} in the last 30
            days. Tap to see {recent === 1 ? "it" : "them"}.
          </span>
        </button>
      ) : (
        <button
          type="button"
          className="text-button"
          onClick={() => setOpen(true)}
        >
          Wallet alarms
        </button>
      )}
      {open && (
        <Sheet
          title="Wallet alarms"
          eyebrow="Clan wallet"
          onClose={() => setOpen(false)}
        >
          <AlarmList clanId={clanId} view={view} />
        </Sheet>
      )}
    </>
  );
}
/** Shown above the sign button when money recently left this wallet generation unexpectedly. */
export function SpendAlarmWarning({
  clanId,
  generation,
}: {
  clanId: string;
  generation: number | null;
}) {
  const { alarms, error } = useWalletAlarms(clanId);
  if (error)
    return (
      <p className="fine-print" role="status">
        Could not check wallet alarms. If you are unsure, check with{" "}
        {communityName()} before you sign.
      </p>
    );
  if (!alarms || !recentSpendAlarm(alarms, generation)) return null;
  return (
    <div className="live-alert error" role="alert">
      <WarningCircle size={20} />
      <span>
        Money left this wallet without an approved payout. Check with{" "}
        {communityName()} before you sign.
      </span>
    </div>
  );
}
