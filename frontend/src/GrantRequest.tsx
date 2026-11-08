import { useEffect, useState } from "react";
import { ArrowRight, ArrowLeft } from "@phosphor-icons/react";
import { api } from "./live-api";
import { useRegion } from "./Region";
import { Busy, satsLabel } from "./ui";

type Quote = {
  quote: string;
  amount_sats: number;
  amount_minor: number;
  currency: string;
  expires_at: number;
  source: string;
};
export function GrantRequest({
  clanId,
  requestKey,
  busy,
  run,
  onSent,
}: {
  clanId: string;
  requestKey: string;
  busy: boolean;
  run: (work: () => Promise<void>) => Promise<void>;
  onSent: () => Promise<void>;
}) {
  const { currency, locale } = useRegion();
  const [amount, setAmount] = useState("");
  const [purpose, setPurpose] = useState("");
  const [quote, setQuote] = useState<Quote | null>(null);
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  const expired = !!quote && quote.expires_at * 1000 <= now;
  return (
    <form
      className="local-grant-form"
      onSubmit={(event) => {
        event.preventDefault();
        void run(async () => {
          if (!quote || expired) {
            setQuote(
              await api<Quote>(`/clans/${clanId}/grant-quote`, {
                currency,
                amount,
              }),
            );
          } else {
            await api(
              `/clans/${clanId}/grants`,
              { purpose, quote: quote.quote },
              requestKey,
            );
            await onSent();
          }
        });
      }}
    >
      {quote ? (
        <>
          <button
            type="button"
            className="text-button"
            disabled={busy}
            onClick={() => setQuote(null)}
          >
            <ArrowLeft size={18} />
            Change amount
          </button>
          <div className="grant-quote-review">
            <span className="eyebrow">You are asking for</span>
            <h3>
              {quote.currency}{" "}
              {new Intl.NumberFormat(locale, {
                maximumFractionDigits: 2,
              }).format(quote.amount_minor / 100)}
            </h3>
            <p>{purpose}</p>
          </div>
          <p className="field-help">
            This is {satsLabel(quote.amount_sats)} at the {quote.source} Bitcoin
            rate.{" "}
            {quote.currency === "KES"
              ? "You would owe your clan this KES amount. Each repayment counts in KES at the rate when it arrives."
              : "Your grant and repayments follow this Bitcoin amount, so its local value can change."}
          </p>
          <p className="field-help">
            {expired
              ? "This rate has expired. Check the amount again."
              : "Your members vote first. Signatories then approve the payment."}
          </p>
        </>
      ) : (
        <>
          <p className="lead">
            Tell your clan what you need and what it will help you do.
          </p>
          <label>
            Amount in {currency}
            <input
              name="amount"
              inputMode="decimal"
              type="text"
              pattern="[0-9]+([.][0-9]{1,2})?"
              maxLength={15}
              required
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
              placeholder="0.00"
              autoComplete="off"
            />
          </label>
          <p className="field-help">
            Use a dot for cents, for example 1500.50. Change currency in
            Profile.
          </p>
          <label>
            What will it help you do?
            <textarea
              name="purpose"
              required
              minLength={8}
              maxLength={1000}
              rows={4}
              value={purpose}
              onChange={(event) => setPurpose(event.target.value)}
            />
          </label>
          <p className="field-help">
            A grant must be repaid to the clan. You will see the amount before
            you send your request.
          </p>
        </>
      )}
      <button className="primary-button" disabled={busy}>
        <Busy busy={busy}>
          {!quote || expired ? "Check amount" : "Send request"}
        </Busy>
        <ArrowRight size={20} />
      </button>
    </form>
  );
}
