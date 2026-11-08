import { useEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, ArrowClockwise } from "@phosphor-icons/react";
import { api, type ActivityItem } from "./live-api";
import { activityCategory, activityTitle } from "./ActivityDetail";
import { Busy } from "./ui";
import { useRegion } from "./Region";
import { localMoney, useRate } from "./LocalMoney";
type Item = ActivityItem;
type Page = { items: Item[]; next_cursor: string | null };
function monthKey(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}
export function ActivityScreen({
  clanId,
  clanName,
  labels,
  pending,
  onOpen,
}: {
  clanId: string;
  clanName: string;
  labels: Record<string, string>;
  pending: React.ReactNode;
  onOpen: (item: Item) => void;
}) {
  const { locale, currency } = useRegion();
  const dateLocale = navigator.language || "en";
  const { rate, unavailable } = useRate(currency);
  const [month, setMonth] = useState(() => monthKey(new Date()));
  const [data, setData] = useState<Page | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  const path = `/clans/${clanId}/activity?month=${month}&timezone=${encodeURIComponent(timezone)}`;
  const activePath = useRef(path);
  activePath.current = path;
  useEffect(() => {
    let active = true;
    setData(null);
    setError("");
    setBusy(true);
    api<Page>(path)
      .then((value) => {
        if (active) setData(value);
      })
      .catch((e) => {
        if (active) setError(e.message);
      })
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, [path, reload]);
  async function more() {
    if (!data?.next_cursor || busy) return;
    const currentPath = path;
    setBusy(true);
    setError("");
    try {
      const next = await api<Page>(
        path + "&cursor=" + encodeURIComponent(data.next_cursor),
      );
      setData((old) =>
        old && currentPath === activePath.current
          ? {
              items: [
                ...old.items,
                ...next.items.filter(
                  (item) => !old.items.some((prior) => prior.id === item.id),
                ),
              ],
              next_cursor: next.next_cursor,
            }
          : old,
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function move(delta: number) {
    const [year, number] = month.split("-").map(Number);
    setMonth(monthKey(new Date(year, number - 1 + delta, 1)));
  }
  const date = new Date(
    Number(month.slice(0, 4)),
    Number(month.slice(5)) - 1,
    1,
  );
  const monthName = date.toLocaleDateString(dateLocale, {
    month: "long",
    year: "numeric",
  });
  function description(item: Item) {
    const title = activityTitle(item, labels);
    const { icon: Icon } = activityCategory(item.category);
    const raw =
      item.data.amount_msat ??
      (typeof item.data.amount_sats === "number" &&
      Number.isSafeInteger(item.data.amount_sats)
        ? String(item.data.amount_sats * 1000)
        : null);
    const amount =
      typeof raw === "string" && /^\d{1,24}$/.test(raw) ? raw : null;
    const direction =
      item.event === "grant_disbursed"
        ? "out"
        : [
              "treasury_settled",
              "deposit_received",
              "repayment_received",
            ].includes(item.event)
          ? "in"
          : "request";
    const value = amount
      ? rate
        ? localMoney(amount, rate, true, locale)
        : `${new Intl.NumberFormat(locale, { maximumFractionDigits: 3 }).format(Number(amount) / 1000)} sats`
      : null;
    return { title, Icon, direction, value };
  }
  return (
    <section className="content-page monthly-activity">
      <div className="ledger-heading">
        <div>
          <p>{clanName}</p>
          <h1>Activity</h1>
        </div>
        <button
          className="icon-button"
          aria-label="Refresh activity"
          disabled={busy}
          onClick={() => setReload((n) => n + 1)}
        >
          <ArrowClockwise size={22} />
        </button>
      </div>
      <div className="month-picker ledger-month">
        <button
          className="icon-button"
          aria-label="Previous month"
          disabled={busy || month <= "2000-01"}
          onClick={() => move(-1)}
        >
          <ArrowLeft size={21} />
        </button>
        <label>
          <span className="sr-only">Activity month</span>
          <span aria-hidden="true">{monthName}</span>
          <input
            type="month"
            value={month}
            min="2000-01"
            max={monthKey(new Date())}
            disabled={busy}
            onChange={(event) => {
              if (/^\d{4}-(0[1-9]|1[0-2])$/.test(event.target.value))
                setMonth(event.target.value);
            }}
          />
        </label>
        <button
          className="icon-button"
          aria-label="Next month"
          disabled={busy || month >= monthKey(new Date())}
          onClick={() => move(1)}
        >
          <ArrowRight size={21} />
        </button>
      </div>
      {error && (
        <p role="alert" className="field-help">
          {error}{" "}
          <button
            className="text-button"
            disabled={busy}
            onClick={() => setReload((n) => n + 1)}
          >
            Try again
          </button>
        </p>
      )}
      {!data && busy && (
        <div className="activity-skeleton" role="status">
          <Busy busy>Loading this month</Busy>
          <i />
          <i />
          <i />
        </div>
      )}
      {data && (
        <div
          className="activity-list ledger-list"
          aria-label={monthName}
          aria-busy={busy}
        >
          <div className="ledger-columns" aria-hidden="true">
            <span>This month</span>
            <span>Amount</span>
          </div>
          {data.items.map((item) => {
            const { title, Icon, direction, value } = description(item);
            const occurred = new Date(item.at);
            const today = occurred.toDateString() === new Date().toDateString();
            return (
              <button
                type="button"
                key={item.id}
                className="ledger-row"
                onClick={() => onOpen(item)}
              >
                <Icon
                  className={
                    item.category === "security"
                      ? "ledger-icon ledger-security"
                      : "ledger-icon"
                  }
                  size={26}
                  aria-hidden="true"
                />
                <span className="ledger-event">
                  <span className="ledger-title">{title}</span>
                  <span className="ledger-meta">
                    {item.actor}
                    {" · "}
                    <time dateTime={item.at}>
                      {today
                        ? "Today"
                        : occurred.toLocaleDateString(dateLocale, {
                            day: "numeric",
                            month: "short",
                          })}
                      {", "}
                      {occurred.toLocaleTimeString(dateLocale, {
                        hour: "2-digit",
                        hour12: false,
                        minute: "2-digit",
                      })}
                    </time>
                  </span>
                </span>
                {value && (
                  <span className={`ledger-amount ledger-${direction}`}>
                    <span
                      className={
                        direction === "request"
                          ? "ledger-request-label"
                          : "sr-only"
                      }
                    >
                      {direction === "request"
                        ? item.category === "wallet"
                          ? "Amount"
                          : "Requested"
                        : direction === "in"
                          ? "Money in"
                          : "Money out"}
                    </span>
                    <strong>
                      {direction === "request"
                        ? ""
                        : direction === "in"
                          ? "+ "
                          : "− "}
                      {value}
                    </strong>
                  </span>
                )}
              </button>
            );
          })}
          {!data.items.length && (
            <div className="empty-state">
              <p>No activity this month.</p>
            </div>
          )}
          {!!data.items.length && !data.next_cursor && (
            <p className="ledger-end">
              End of {date.toLocaleDateString(dateLocale, { month: "long" })}{" "}
              activity
            </p>
          )}
        </div>
      )}
      {data?.next_cursor && (
        <button
          className="secondary-button"
          disabled={busy}
          onClick={() => void more()}
        >
          <Busy busy={busy}>Load more from this month</Busy>
        </button>
      )}
      <p className="ledger-rate fine-print">
        {rate
          ? `${currency} values use the current Bitcoin rate and can change.`
          : unavailable
            ? `${currency} rate unavailable. Showing sats.`
            : `Getting the ${currency} rate. Showing sats for now.`}
      </p>
      <details className="ledger-requests">
        <summary>Grant requests</summary>
        {pending}
      </details>
    </section>
  );
}
