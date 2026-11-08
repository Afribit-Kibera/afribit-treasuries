import { useEffect, useState } from "react";
import QRCode from "qrcode";
import {
  ArrowLeft,
  CheckCircle,
  Hourglass,
  Storefront,
  WarningCircle,
} from "@phosphor-icons/react";
import { Sheet, Busy } from "./ui";
import { CopyButton } from "./CopyButton";
import { WalletStop } from "./WalletCompare";
import { useRegion } from "./Region";
import { useRate } from "./LocalMoney";
import { useWalletReceipts } from "./useWalletReceipts";
import { walletMessage } from "./wallet-trust";
import { bitcoinAmount, checkedAddress, stopsPayment } from "./WalletDeposit";
import {
  isKesDebt,
  kesMinor,
  owedLabel,
  parseKes,
  satsForKes,
} from "./grant-debt";
import type { Grant } from "./live-api";
import type { WalletView } from "./wallet-api";

/** KES cents as a value the member can edit: "1500" or "1500.50". */
const kesInput = (minor: number) =>
  minor % 100 ? (minor / 100).toFixed(2) : String(minor / 100);

/**
 * Repaying with cash: the member hands KES to an OTC agent, who sends bitcoin to the
 * grant's own repayment address. Partial payments are fine. The sats shown are only a
 * guide; the payment counts at the rate when the clan's watcher first sees it.
 */
export function WalletAgentPay({
  clanId,
  clanName,
  grant,
  view,
  onBack,
  onClose,
  onConfirmed,
}: {
  clanId: string;
  clanName: string;
  grant: Grant;
  view: WalletView;
  onBack: () => void;
  onClose: () => void;
  onConfirmed?: () => Promise<unknown>;
}) {
  const { locale } = useRegion();
  const { rate, unavailable } = useRate("KES");
  const kesDebt = isKesDebt(grant);
  const owed = kesDebt ? (grant.outstanding_minor ?? 0) : 0;
  const [cash, setCash] = useState(owed > 0 ? kesInput(owed) : ""),
    [address, setAddress] = useState(""),
    [qr, setQr] = useState(""),
    [uri, setUri] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [stop, setStop] = useState("");
  const cashMinor = parseKes(cash);
  const guide =
    rate && cashMinor && cashMinor > 0n ? satsForKes(cashMinor, rate) : null;
  const number = (value: number | bigint) =>
    new Intl.NumberFormat(locale).format(value);
  const receipts = useWalletReceipts({
    clanId,
    address,
    purpose: "repayment",
    grantId: grant.id,
    // Keep checking until a payment is counted; the agent may send any amount.
    amount: 1n,
    onConfirmed,
    interval: 10000,
  });
  useEffect(() => {
    if (!address) return;
    let alive = true;
    // With a rate, the code carries the guide amount; the agent can still change it.
    const payment = guide
      ? `bitcoin:${address}?amount=${bitcoinAmount(guide)}`
      : `bitcoin:${address}`;
    void QRCode.toDataURL(payment, {
      width: 480,
      margin: 2,
      errorCorrectionLevel: "M",
    }).then((image) => {
      if (!alive) return;
      setQr(image);
      setUri(payment);
    });
    return () => {
      alive = false;
    };
  }, [address, guide]);

  const fresh = receipts.fresh;
  const seen = fresh.filter((r) => r.status === "pending");
  const counted = fresh.filter((r) => r.status === "confirmed");
  const dropped = fresh.filter((r) => r.status === "dropped");
  const sats = (rows: typeof fresh) =>
    rows.reduce((sum, r) => sum + BigInt(r.amount_sats), 0n);
  const waitingForRate = seen.some((r) => r.credit_note === "waiting_for_rate");
  const creditedKes = counted.reduce(
    (sum, r) => sum + (r.kes_credited_minor ?? 0),
    0,
  );
  const owedAfter = counted
    .map((r) => r.kes_owed_after_minor)
    .filter((v): v is number => typeof v === "number");
  const stillOwed = kesDebt
    ? kesMinor(
        owedAfter.length
          ? Math.min(...owedAfter, grant.outstanding_minor ?? owedAfter[0])
          : (grant.outstanding_minor ?? 0),
        locale,
      )
    : owedLabel(grant, locale);
  const repaid =
    grant.status === "recovered" ||
    (kesDebt && owedAfter.length > 0 && Math.min(...owedAfter) === 0);

  return (
    <Sheet
      title="Pay through an agent"
      eyebrow={clanName}
      busy={busy}
      onClose={onClose}
    >
      <div className="wallet-flow agent-pay">
        {stop ? (
          <WalletStop message={stop} />
        ) : !address ? (
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              setError("");
              if (!cashMinor || cashMinor <= 0n) {
                setError("Enter the cash in KES, for example 500.");
                return;
              }
              setBusy(true);
              try {
                setAddress(
                  await checkedAddress(clanId, view, "repayment", grant.id),
                );
              } catch (e) {
                const message = walletMessage(e);
                if (stopsPayment(message)) setStop(message);
                else setError(message);
              } finally {
                setBusy(false);
              }
            }}
          >
            <button
              type="button"
              className="text-button"
              disabled={busy}
              onClick={onBack}
            >
              <ArrowLeft size={18} /> Other ways to repay
            </button>
            <p className="lead">
              Give the cash to an agent. The agent sends bitcoin to your
              grant’s code. You can pay part now and the rest later.
            </p>
            <p>
              Still owed: <strong>{owedLabel(grant, locale)}</strong>
            </p>
            {error && <p role="alert">{error}</p>}
            <label>
              Cash you are giving the agent (KES)
              <input
                value={cash}
                onChange={(e) => setCash(e.target.value)}
                inputMode="decimal"
                pattern="[0-9]+([.][0-9]{1,2})?"
                maxLength={12}
                required
                disabled={busy}
                autoComplete="off"
              />
            </label>
            <p className="field-help">
              {guide
                ? `About ${number(guide)} sats at today’s rate. The agent’s own rate may differ.`
                : unavailable
                  ? "Today’s rate isn’t available, so we can’t show the sats. The agent can still pay."
                  : "Checking today’s rate…"}
            </p>
            {kesDebt && cashMinor !== null && cashMinor > BigInt(owed) && (
              <p className="field-help">
                This is more than you owe. Anything extra stays with your clan.
              </p>
            )}
            <button className="primary-button" disabled={busy}>
              <Busy busy={busy}>
                <Storefront size={20} /> Show the code to the agent
              </Busy>
            </button>
          </form>
        ) : (
          <>
            <button
              type="button"
              className="text-button"
              onClick={() => setAddress("")}
            >
              <ArrowLeft size={18} /> Change the amount
            </button>
            <div className="payment-heading">
              <p>Cash to the agent</p>
              <h3>{cashMinor ? kesMinor(cashMinor, locale) : ""}</h3>
              {guide && (
                <p className="fine-print">
                  About {number(guide)} sats. The agent’s own rate may differ.
                </p>
              )}
            </div>
            <AgentStatus
              repaid={repaid}
              seen={sats(seen)}
              counted={sats(counted)}
              waitingForRate={waitingForRate}
              confirmations={Math.max(0, ...seen.map((r) => r.confirmations))}
              required={view.confirmations_required ?? 3}
              creditedKes={kesDebt ? kesMinor(creditedKes, locale) : ""}
              stillOwed={stillOwed}
              number={number}
            />
            {dropped.length > 0 && (
              <p role="alert">
                <WarningCircle size={20} /> A payment is no longer seen on the
                network. Ask the agent to check it before paying again.
              </p>
            )}
            {receipts.error && (
              <p role="alert">
                {receipts.error} Please don’t pay again while this is unclear.
              </p>
            )}
            {counted.length === 0 && (
              <>
                <div className="qr-frame agent-qr">
                  {qr ? (
                    <img
                      className="deposit-qr"
                      src={qr}
                      width={480}
                      height={480}
                      alt="Bitcoin code for the agent to scan"
                    />
                  ) : (
                    <span className="qr-placeholder">
                      <Busy busy>Making the code</Busy>
                    </span>
                  )}
                </div>
                <p className="field-help">
                  The agent can send any amount. Every payment to this code
                  counts towards your grant.
                </p>
                <p className="wallet-address agent-address">
                  {address.match(/.{1,4}/g)?.join(" ")}
                </p>
                <CopyButton
                  value={address}
                  label="Copy Bitcoin address"
                  message="Bitcoin address copied"
                />
                {uri && (
                  <p className="fine-print">
                    {view.network === "bitcoin"
                      ? "Real bitcoin. The agent must send to this address only."
                      : "Test network only. The agent must not send real bitcoin."}
                  </p>
                )}
              </>
            )}
            <button
              className="secondary-button"
              disabled={receipts.checking}
              onClick={receipts.refresh}
            >
              <Busy busy={receipts.checking}>Check again</Busy>
            </button>
          </>
        )}
      </div>
    </Sheet>
  );
}

function AgentStatus({
  repaid,
  seen,
  counted,
  waitingForRate,
  confirmations,
  required,
  creditedKes,
  stillOwed,
  number,
}: {
  repaid: boolean;
  seen: bigint;
  counted: bigint;
  waitingForRate: boolean;
  confirmations: number;
  required: number;
  creditedKes: string;
  stillOwed: string;
  number: (value: number | bigint) => string;
}) {
  if (counted > 0n)
    return (
      <div role="status" className="agent-status agent-status-done">
        <p className="payment-status">
          <CheckCircle size={22} /> Confirmed
        </p>
        <p>
          {creditedKes
            ? `${creditedKes} counted towards your grant.`
            : `${number(counted)} sats counted towards your grant.`}{" "}
          {repaid
            ? "Your grant is fully repaid. Thank you."
            : `${stillOwed} still owed.`}
        </p>
        {seen > 0n && (
          <p className="fine-print">
            Another payment of {number(seen)} sats is waiting for confirmation.
          </p>
        )}
      </div>
    );
  if (seen > 0n)
    return (
      <div role="status" className="agent-status">
        <p className="payment-status">
          <Hourglass size={22} /> Payment seen: {number(seen)} sats
        </p>
        <p>
          {waitingForRate
            ? "It is confirmed. It counts in KES as soon as today’s rate is available."
            : `Waiting for confirmation (${Math.min(confirmations, required)} of ${required}). You can leave the agent now.`}
        </p>
      </div>
    );
  return (
    <div role="status" className="agent-status">
      <p className="payment-status">
        <Hourglass size={22} /> Waiting for the agent’s payment
      </p>
      <p>
        Stay with the agent until this screen shows the payment as seen. It
        usually takes a minute or two.
      </p>
    </div>
  );
}
