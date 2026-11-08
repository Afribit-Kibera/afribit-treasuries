import {
  useEffect,
  useState,
  type FormEvent,
  type ComponentProps,
} from "react";
import { useClanWallet } from "./useClanWallet";
import { WalletGrantMoney } from "./WalletGrantMoney";
import { WalletDeposit } from "./WalletDeposit";
import { getWallet } from "./wallet-api";
import { isKesDebt, kesMinor, owedEstimate, owedLabel } from "./grant-debt";
import QRCode from "qrcode";
import { CircleNotch, CheckCircle, HandCoins } from "@phosphor-icons/react";
import { useRegion } from "./Region";
import { localMoney, useRate } from "./LocalMoney";
import { satsLabel } from "./ui";
import { startAuthentication } from "@simplewebauthn/browser";
import type { PublicKeyCredentialRequestOptionsJSON } from "@simplewebauthn/browser";
import { api, ApiError, type Deposit, type Grant } from "./live-api";
import { Sheet, Busy } from "./ui";
import { WalletChooser } from "./WalletChooser";

type Run = (work: () => Promise<void>) => Promise<void>;
export function msats(value: string = "0") {
  const amount = BigInt(value);
  const whole = amount / 1000n;
  const fraction = (amount % 1000n)
    .toString()
    .padStart(3, "0")
    .replace(/0+$/, "");
  return `${whole.toLocaleString()}${fraction ? "." + fraction : ""} sats`;
}
export function DepositSheet(
  props: ComponentProps<typeof LightningDepositSheet> & {
    /** The grant being repaid, for what is still owed and the cash-agent option. */
    grant?: Grant;
  },
) {
  const wallet = useClanWallet(props.clanId);
  const [lightning, setLightning] = useState(false);
  if (wallet.loading || wallet.error || !wallet.view)
    return (
      <Sheet title="Add money" onClose={props.onClose}>
        <div className="wallet-flow">
          {wallet.loading ? (
            <Busy busy>Checking the clan wallet</Busy>
          ) : (
            <>
              <p role="alert">
                {wallet.error || "The clan wallet could not be checked."}
              </p>
              <button
                className="secondary-button"
                onClick={() => void wallet.refresh()}
              >
                Try again
              </button>
            </>
          )}
        </div>
      </Sheet>
    );
  if (wallet.view.enabled && wallet.view.status === "active")
    return lightning ? (
      <LightningDepositSheet {...props} existing={undefined} requireTill />
    ) : (
      <WalletDeposit
        clanId={props.clanId}
        clanName={props.clanName}
        grantId={props.grantId}
        view={wallet.view}
        onClose={props.onClose}
        onLightning={() => setLightning(true)}
        grant={props.grant}
        onConfirmed={async () => {
          wallet.setView(await getWallet(props.clanId));
          await props.onRefresh();
        }}
      />
    );
  return <LightningDepositSheet {...props} />;
}
function LightningDepositSheet({
  clanId,
  clanName,
  grantId,
  existing,
  max,
  busy,
  run,
  onClose,
  onRefresh,
  requireTill = false,
}: {
  clanId: string;
  clanName: string;
  grantId?: string;
  existing?: Deposit;
  max: number;
  busy: boolean;
  run: Run;
  onClose: () => void;
  onRefresh: () => Promise<unknown>;
  requireTill?: boolean;
}) {
  const { currency, locale } = useRegion();
  const { rate } = useRate(currency);
  const [deposit, setDeposit] = useState<Deposit | undefined>(existing);
  const [requestId, setRequestId] = useState(existing?.id || "");
  const [key] = useState(() => crypto.randomUUID());
  const [amount, setAmount] = useState("");
  const [unit, setUnit] = useState(currency);
  const [quote, setQuote] = useState<{
    quote: string;
    amount_sats: number;
    amount_minor: number;
    currency: string;
    expires_at: number;
  } | null>(null);
  const [qr, setQr] = useState("");
  const [pollError, setPollError] = useState(false);
  const [checking, setChecking] = useState(false);
  const [checkNumber, setCheckNumber] = useState(0);
  const [now, setNow] = useState(Date.now());
  const [submitted, setSubmitted] = useState(false);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    if (!requestId) return;
    let active = true,
      running = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      if (!active || running) return;
      clearTimeout(timer);
      running = true;
      setChecking(true);
      let finished = false;
      try {
        const next = await api<Deposit & { method?: string }>(
          `/clans/${clanId}/deposits/${requestId}`,
        );
        if (requireTill && next.method !== "lightning")
          throw Error(
            "This Lightning payment could not be checked. Close this screen and use the clan’s Bitcoin address.",
          );
        if (!active) return;
        setDeposit(next);
        setPollError(false);
        if (next.status === "settled") {
          finished = true;
          await onRefresh();
        }
        if (next.status === "review_required") finished = true;
      } catch {
        if (active) setPollError(true);
      } finally {
        running = false;
        if (active) {
          setChecking(false);
          if (!finished) timer = setTimeout(poll, 5000);
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
      active = false;
      clearTimeout(timer);
      window.removeEventListener("focus", resume);
      document.removeEventListener("visibilitychange", resume);
    };
  }, [requestId, clanId, onRefresh, checkNumber, requireTill]);
  useEffect(() => {
    let active = true;
    setQr("");
    if (deposit?.bolt11)
      QRCode.toDataURL(`lightning:${deposit.bolt11}`, {
        width: 320,
        margin: 3,
        errorCorrectionLevel: "M",
      })
        .then((value) => {
          if (active) setQr(value);
        })
        .catch(() => {});
    return () => {
      active = false;
    };
  }, [deposit?.bolt11]);
  const expired =
    deposit?.status === "expired" ||
    (!!deposit?.expires_at && Date.parse(deposit.expires_at) <= now);
  const repaying = !!(grantId || deposit?.grant_id);
  const quoteExpired = !!quote && quote.expires_at * 1000 <= now;
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void run(async () => {
      if (!submitted && unit !== "SATS" && (!quote || quoteExpired)) {
        setQuote(
          await api(`/clans/${clanId}/deposit-quote`, {
            currency: unit,
            amount,
          }),
        );
        return;
      }
      setSubmitted(true);
      try {
        const result = await api<{ request_id: string; method?: string }>(
          `/clans/${clanId}/deposits`,
          {
            ...(unit === "SATS"
              ? { amount_sats: Number(amount) }
              : { quote: quote!.quote }),
            grant_id: grantId || null,
          },
          key,
        );
        if (requireTill && result.method !== "lightning")
          throw Error(
            "Lightning is not available for this amount. Close this screen and use the clan’s Bitcoin address.",
          );
        setRequestId(result.request_id);
        await onRefresh();
      } catch (error) {
        // Only a definite server rejection unlocks editing. A lost response must
        // retry the same key and amount, including after the quote expires.
        if (
          error instanceof ApiError &&
          error.status >= 400 &&
          error.status < 500 &&
          error.status !== 408
        )
          setSubmitted(false);
        throw error;
      }
    });
  }
  return (
    <Sheet
      title={repaying ? "Repay your clan" : "Add money"}
      eyebrow={clanName}
      onClose={onClose}
      busy={busy}
    >
      <div className="payment-flow">
        <ol className="payment-steps" aria-label="Payment progress">
          {[
            "Amount",
            deposit?.status === "review_required" ? "On hold" : "Pay",
            "Done",
          ].map((label, index) => (
            <li
              key={label}
              aria-current={
                index ===
                (deposit?.status === "settled" ? 2 : requestId ? 1 : 0)
                  ? "step"
                  : undefined
              }
            >
              <span>{index + 1}</span>
              {label}
            </li>
          ))}
        </ol>
        {!requestId ? (
          <form onSubmit={submit} className="money-form">
            <div className="payment-symbol">
              <HandCoins size={40} />
            </div>
            <p className="lead">
              {repaying
                ? "Pay a little or pay it all. Each payment reduces what you owe."
                : "Choose an amount to add to your shared money."}
            </p>
            {quote ? (
              <div className="payment-amount">
                <span>You will pay</span>
                <h3>
                  {quote.currency}{" "}
                  {new Intl.NumberFormat(locale).format(
                    quote.amount_minor / 100,
                  )}
                </h3>
                <p>{satsLabel(quote.amount_sats)}</p>
                {!submitted && (
                  <button
                    type="button"
                    className="text-button"
                    disabled={busy}
                    onClick={() => setQuote(null)}
                  >
                    Change amount
                  </button>
                )}
                <p className="fine-print">
                  {quoteExpired
                    ? "This rate expired. Check the amount again."
                    : "The Bitcoin amount is fixed when you create the request."}
                </p>
              </div>
            ) : (
              <>
                <label>
                  Pay in
                  <select
                    value={unit}
                    disabled={submitted}
                    onChange={(event) => setUnit(event.target.value)}
                  >
                    <option value={currency}>{currency}</option>
                    <option value="SATS">Bitcoin (sats)</option>
                  </select>
                </label>
                <label>
                  Amount in {unit === "SATS" ? "sats" : unit}
                  <input
                    name="amount"
                    type="text"
                    inputMode={unit === "SATS" ? "numeric" : "decimal"}
                    pattern={
                      unit === "SATS" ? "[0-9]+" : "[0-9]+([.][0-9]{1,2})?"
                    }
                    maxLength={15}
                    required
                    value={amount}
                    readOnly={submitted}
                    onChange={(event) => setAmount(event.target.value)}
                    placeholder="0.00"
                    autoComplete="off"
                  />
                </label>
                <p className="field-help">
                  {unit === "SATS"
                    ? `Up to ${max.toLocaleString(locale)} sats per request.`
                    : "Use a dot for cents, for example 1500.50. We show the Bitcoin amount before you pay."}
                </p>
              </>
            )}
            <button className="primary-button" disabled={busy} type="submit">
              <Busy busy={busy}>
                {!submitted && unit !== "SATS" && (!quote || quoteExpired)
                  ? "Check amount"
                  : submitted
                    ? "Try the same request again"
                    : "Create payment request"}
              </Busy>
            </button>
            {submitted && (
              <p className="field-help">
                If the connection stopped, retry here. We keep the same request
                so you do not create another bill.
              </p>
            )}
          </form>
        ) : deposit?.status === "settled" ? (
          <div className="payment-result" role="status">
            <CheckCircle size={64} weight="duotone" />
            <h3>Money received</h3>
            <p className="payment-amount">
              {rate
                ? localMoney(
                    String(deposit.credited_sats * 1000),
                    rate,
                    true,
                    locale,
                  )
                : satsLabel(deposit.credited_sats)}
            </p>
            <p>
              {repaying
                ? "Your repayment is recorded. Any extra stays in your clan."
                : "Your clan balance is up to date."}
            </p>
            <button className="primary-button" onClick={onClose}>
              Done
            </button>
          </div>
        ) : deposit?.status === "review_required" ? (
          <div className="payment-result" role="status">
            <h3>This request needs a check</h3>
            <p>
              Please do not pay this request. If you have paid, keep your
              payment receipt and contact Afribit. Your payment will be checked
              before it is added.
            </p>
            <button className="primary-button" onClick={onClose}>
              Close
            </button>
          </div>
        ) : !deposit?.bolt11 && !expired ? (
          <div className="payment-result" role="status" aria-live="polite">
            <CircleNotch className="spin" size={52} />
            <h3>
              {pollError ? "Trying to reconnect" : "Getting your request ready"}
            </h3>
            <p>
              {pollError
                ? "Please keep this request. We will check again."
                : "This can take a moment. You can return to it from Home."}
            </p>
            <button
              className="secondary-button"
              disabled={checking}
              onClick={() => setCheckNumber((n) => n + 1)}
            >
              <Busy busy={checking}>Check again</Busy>
            </button>
          </div>
        ) : (
          <>
            <div className="payment-amount">
              <span>{repaying ? "Your repayment" : "Add to " + clanName}</span>
              <h3>
                {rate && deposit
                  ? localMoney(
                      String(deposit.amount_sats * 1000),
                      rate,
                      true,
                      locale,
                    )
                  : deposit
                    ? satsLabel(deposit.amount_sats)
                    : "Payment request"}
              </h3>
              {rate && deposit && (
                <p>{satsLabel(deposit.amount_sats)} - current estimate</p>
              )}
            </div>
            <p role="status" className="payment-status">
              {pollError
                ? "Connection lost. We will keep checking. Please do not pay again."
                : expired
                  ? "This request expired. We still check for late payments."
                  : "Waiting for payment"}
            </p>
            {deposit?.bolt11 && !expired && (
              <>
                <div className="qr-frame">
                  {qr ? (
                    <img
                      className="deposit-qr"
                      src={qr}
                      width="320"
                      height="320"
                      alt={`Payment request for ${deposit.amount_sats} sats`}
                    />
                  ) : (
                    <div className="qr-placeholder" role="status">
                      <Busy busy>Preparing QR code</Busy>
                    </div>
                  )}
                </div>
                <WalletChooser
                  invoice={deposit.bolt11}
                  onPaymentSubmitted={() => setCheckNumber((n) => n + 1)}
                />
                {deposit.checkout_url && (
                  <a
                    className="text-button"
                    href={deposit.checkout_url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Open payment page
                  </a>
                )}
                <p className="fine-print">
                  Pay once. Expires{" "}
                  {deposit.expires_at &&
                    new Date(deposit.expires_at).toLocaleTimeString(locale, {
                      hour: "numeric",
                      minute: "2-digit",
                    })}
                  . When you return from your wallet, we check automatically.
                </p>
              </>
            )}
            <button
              className="secondary-button"
              disabled={checking}
              onClick={() => setCheckNumber((n) => n + 1)}
            >
              <Busy busy={checking}>Check payment</Busy>
            </button>
            {expired && (
              <p className="fine-print">
                Check your wallet before starting another payment.
              </p>
            )}
          </>
        )}
      </div>
    </Sheet>
  );
}

export function GrantMoney(
  props: ComponentProps<typeof LightningGrantMoney> & {
    onCheckWallet?: () => void;
  },
) {
  const wallet = useClanWallet(props.clanId);
  if (wallet.loading) return <Busy busy>Checking the clan wallet</Busy>;
  if (wallet.error || !wallet.view)
    return (
      <div className="wallet-flow">
        <p role="alert">
          {wallet.error || "The clan wallet could not be checked."}
        </p>
        <button
          className="secondary-button"
          onClick={() => void wallet.refresh()}
        >
          Try again
        </button>
      </div>
    );
  if (wallet.view.enabled && wallet.view.status === "active")
    return (
      <WalletGrantMoney
        {...props}
        view={wallet.view}
        onRefresh={async () => {
          wallet.setView(await getWallet(props.clanId));
          await props.onRefresh();
        }}
      />
    );
  return <LightningGrantMoney {...props} />;
}
function LightningGrantMoney({
  clanId,
  grant,
  isBeneficiary,
  payoutsEnabled,
  receivingEnabled,
  busy,
  run,
  onRefresh,
  onRepay,
}: {
  clanId: string;
  grant: Grant;
  isBeneficiary: boolean;
  payoutsEnabled: boolean;
  receivingEnabled: boolean;
  busy: boolean;
  run: Run;
  onRefresh: () => Promise<unknown>;
  onRepay: () => void;
}) {
  const [invoice, setInvoice] = useState("");
  const [key, setKey] = useState(() => crypto.randomUUID());
  const payment = grant.payment;
  const maySet =
    isBeneficiary &&
    ["awaiting_funding", "awaiting_signatures"].includes(grant.status);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    void run(async () => {
      await api(
        `/clans/${clanId}/grants/${grant.id}/destination`,
        { bolt11: invoice.trim() },
        key,
      );
      setInvoice("");
      setKey(crypto.randomUUID());
      await onRefresh();
    });
  };
  async function approve() {
    const options = await api<{
      challenge_id: string;
      intent: { digest: string };
      options: PublicKeyCredentialRequestOptionsJSON;
    }>(`/clans/${clanId}/grants/${grant.id}/payment/approval/options`, {});
    if (options.intent.digest !== payment?.digest)
      throw new Error("This payment changed. Open it again before approving.");
    const credential = await startAuthentication({
      optionsJSON: options.options,
    });
    await api(`/clans/${clanId}/grants/${grant.id}/payment/approval/verify`, {
      challenge_id: options.challenge_id,
      credential,
    });
    await onRefresh();
  }
  return (
    <div className="money-form">
      {maySet && payoutsEnabled && (
        <form onSubmit={submit}>
          <label>
            Payment request from your wallet
            <textarea
              required
              value={invoice}
              onChange={(e) => setInvoice(e.target.value)}
              maxLength={12010}
              placeholder="Paste a mainnet Lightning invoice (lnbcâ€¦)"
              autoComplete="off"
              spellCheck={false}
            />
          </label>
          <p className="fine-print">
            Open your wallet and request exactly{" "}
            {grant.amount_sats.toLocaleString()} sats. Give signatories enough
            time to approve. A new invoice needs new approvals.
          </p>
          <button className="primary-button" disabled={busy || !invoice.trim()}>
            <Busy busy={busy}>
              {payment?.status === "awaiting_approvals"
                ? "Use a new invoice"
                : "Save my invoice"}
            </Busy>
          </button>
        </form>
      )}
      {payment && (
        <section className="payment-review" aria-label="Exact payment approval">
          <h3>Payment to {grant.beneficiary_name}</h3>
          <dl>
            <dt>Amount</dt>
            <dd>{msats(payment.amount_msat)}</dd>
            <dt>Highest fee</dt>
            <dd>{msats(payment.fee_limit_msat)}</dd>
            <dt>Signatories</dt>
            <dd>
              {payment.approval_count} of {payment.required_approvals} approvals
            </dd>
            <dt>Status</dt>
            <dd>
              {(
                {
                  awaiting_approvals: "Waiting for approvals",
                  queued: payment.last_error
                    ? "Payment waiting"
                    : "Ready to pay",
                  sending: "Checking payment",
                  settled: "Paid",
                  failed: "Not paid",
                  expired: "Expired",
                  superseded: "Replaced",
                  rejected: "Not paid",
                  cancelled: "Cancelled",
                } as Record<string, string>
              )[payment.status] || "Checking payment"}
            </dd>
            <dt>Pay before</dt>
            <dd>{new Date(payment.expires_at).toLocaleString()}</dd>
          </dl>
          <details className="payment-reference">
            <summary>Payment reference</summary>
            <code>{payment.payment_hash}</code>
          </details>
          <p className="fine-print">
            Approved by{" "}
            {payment.approved_names.length
              ? payment.approved_names.join(", ")
              : "no one yet"}
            .
          </p>
          {payment.can_approve && payoutsEnabled && (
            <>
              <p>
                Approve {msats(payment.amount_msat)} to {grant.beneficiary_name}
                , with a fee of up to {msats(payment.fee_limit_msat)}. The
                payment starts once enough signatories approve.
              </p>
              <p className="fine-print">
                Confirm these details with the member before approving. Your
                passkey records your choice.
              </p>
              <button
                className="primary-button"
                disabled={busy}
                onClick={() => void run(approve)}
              >
                <Busy busy={busy}>Approve this payment</Busy>
              </button>
            </>
          )}
          {payment.approved_by_me && (
            <p className="fine-print">You approved this payment.</p>
          )}
          {payment.status === "queued" &&
          payment.last_error === "clan_verification_required" ? (
            <p role="status">
              Your clan needs a check by Afribit before this payment can go
              through. The money is still set aside. Your organizer can contact
              Afribit for help.
            </p>
          ) : payment.status === "queued" &&
            ["daily_payment_limit", "payment_limit_reached"].includes(
              payment.last_error || "",
            ) ? (
            <p role="status">
              This payment is waiting because it is above a payment limit. We
              will check again. The money is still set aside.
            </p>
          ) : payment.status === "queued" &&
            payment.last_error === "exchange_rate_unavailable" ? (
            <p role="status">
              We are waiting for an up-to-date exchange rate. The money is still
              set aside.
            </p>
          ) : (
            ["queued", "sending", "uncertain"].includes(payment.status) && (
              <p role="status">
                We are checking this payment. The money is set aside until we
                know the result. Please do not send another invoice.
              </p>
            )
          )}
          {payment.last_error === "payment_failed_no_route_or_liquidity" && (
            <p role="status">
              This payment did not go through. The money is available again. The
              member can send a new invoice.
            </p>
          )}
          {payment.fee_paid_msat !== null && (
            <p>Payment fee: {msats(payment.fee_paid_msat)}</p>
          )}
        </section>
      )}
      {BigInt(grant.outstanding_msat || "0") > 0n && (
        <section>
          <h3>Return to your clan</h3>
          <p>
            Still to repay: <strong>{owedLabel(grant)}</strong>
            {owedEstimate(grant) && (
              <small className="fine-print"> ({owedEstimate(grant)})</small>
            )}
          </p>
          <p className="fine-print">
            Repaid so far:{" "}
            {isKesDebt(grant)
              ? kesMinor(
                  Math.max(
                    0,
                    (grant.principal_minor ?? 0) -
                      (grant.outstanding_minor ?? 0),
                  ),
                )
              : msats(grant.recovered_msat)}
          </p>
          {receivingEnabled && (
            <button
              className="secondary-button"
              disabled={busy}
              onClick={onRepay}
            >
              Repay this grant
            </button>
          )}
        </section>
      )}
      {grant.status === "recovered" && (
        <p role="status">This grant is fully repaid.</p>
      )}
    </div>
  );
}
