import { useEffect, useState } from "react";
import QRCode from "qrcode";
import { CheckCircle, Hourglass, Storefront } from "@phosphor-icons/react";
import { Sheet, Busy } from "./ui";
import type { Grant } from "./live-api";
import { kesMinor, owedEstimate, owedLabel } from "./grant-debt";
import { WalletAgentPay } from "./WalletAgentPay";
import { CopyButton } from "./CopyButton";
import { WalletStop } from "./WalletCompare";
import { useWalletMoney } from "./WalletMoney";
import { clanOutput } from "./vault/policy";
import { checkedWallet, walletMessage } from "./wallet-trust";
import { useWalletReceipts } from "./useWalletReceipts";
import {
  getWalletAddress,
  getTill,
  toClanPolicy,
  type TillView,
  type WalletView,
  type AddressPurpose,
} from "./wallet-api";

export function bitcoinAmount(sats: bigint) {
  return `${sats / 100000000n}.${(sats % 100000000n).toString().padStart(8, "0")}`;
}
/** Get a payment address and check, on this phone, that the clan wallet's keys make it. */
export async function checkedAddress(
  clanId: string,
  view: WalletView,
  purpose: AddressPurpose,
  grantId?: string,
) {
  if (!view.enabled || view.status !== "active" || !view.policy)
    throw Error("The clan wallet is not ready. Do not use this address.");
  const policy = toClanPolicy(
    view.me.is_signer ? checkedWallet(clanId, view).policy : view.policy,
  );
  const response = await getWalletAddress(clanId, purpose, grantId);
  if (
    response.keychain !== "external" ||
    !Number.isSafeInteger(response.index) ||
    response.index < 0 ||
    response.index >= 2147483648 ||
    (purpose === "grant_funding" && response.index !== 0) ||
    response.purpose !== purpose ||
    response.grant_id !== (grantId || null) ||
    clanOutput(policy, "external", response.index).address !== response.address
  )
    throw Error(
      "The payment address does not match your clan wallet. Do not send money.",
    );
  return response.address;
}
/** A wallet check failure that must stop the screen, not only show an error. */
export const stopsPayment = (message: string) =>
  /does not match|not ready|Compare the wallet|compare.*code/i.test(message);
export function WalletDeposit({
  clanId,
  clanName,
  grantId,
  view,
  onClose,
  onLightning,
  onConfirmed,
  purpose: requestedPurpose,
  grant,
}: {
  clanId: string;
  clanName: string;
  grantId?: string;
  view: WalletView;
  onClose: () => void;
  onLightning?: () => void;
  onConfirmed?: () => Promise<unknown>;
  purpose?: AddressPurpose;
  /** The grant being repaid, for what is still owed and the cash-agent option. */
  grant?: Grant;
}) {
  const [agent, setAgent] = useState(false);
  if (agent && grant && grantId)
    return (
      <WalletAgentPay
        clanId={clanId}
        clanName={clanName}
        grant={grant}
        view={view}
        onBack={() => setAgent(false)}
        onClose={onClose}
        onConfirmed={onConfirmed}
      />
    );
  return (
    <WalletAddressPay
      clanId={clanId}
      clanName={clanName}
      grantId={grantId}
      view={view}
      onClose={onClose}
      onLightning={onLightning}
      onConfirmed={onConfirmed}
      purpose={requestedPurpose}
      grant={grant}
      onAgent={() => setAgent(true)}
    />
  );
}
function WalletAddressPay({
  clanId,
  clanName,
  grantId,
  view,
  onClose,
  onLightning,
  onConfirmed,
  purpose: requestedPurpose,
  grant,
  onAgent: setAgent,
}: {
  clanId: string;
  clanName: string;
  grantId?: string;
  view: WalletView;
  onClose: () => void;
  onLightning?: () => void;
  onConfirmed?: () => Promise<unknown>;
  purpose?: AddressPurpose;
  grant?: Grant;
  onAgent: (on: boolean) => void;
}) {
  const [amount, setAmount] = useState(""),
    [address, setAddress] = useState(""),
    [uri, setUri] = useState(""),
    [qr, setQr] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [stop, setStop] = useState(""),
    [till, setTill] = useState<TillView | null>(null),
    [tillError, setTillError] = useState(""),
    [reload, setReload] = useState(0),
    [selectedPurpose, setSelectedPurpose] = useState<AddressPurpose>(
      requestedPurpose || (grantId ? "repayment" : "contribution"),
    );
  const money = useWalletMoney();
  const sats = /^\d+$/.test(amount) ? BigInt(amount) : 0n;
  const purpose = selectedPurpose;
  const receipts = useWalletReceipts({
    clanId,
    address,
    purpose,
    grantId,
    amount: sats,
    onConfirmed,
  });
  useEffect(() => {
    let alive = true;
    setTillError("");
    void getTill(clanId)
      .then((v) => {
        if (alive) setTill(v);
      })
      .catch((e) => {
        if ((e as { status?: number }).status === 404) return;
        if (alive) setTillError("Lightning payments could not be checked.");
      });
    return () => {
      alive = false;
    };
  }, [clanId, reload]);
  const availableTill = !!till?.enabled && till.balance_sats < till.cap_sats;
  const confirmed = receipts.received >= sats && sats > 0n;
  return (
    <Sheet
      title={
        grantId
          ? "Repay your clan"
          : purpose === "grant_funding"
            ? "Fund the clan"
            : "Add money"
      }
      eyebrow={clanName}
      busy={busy}
      onClose={onClose}
    >
      <div className="wallet-flow">
        {stop ? (
          <WalletStop message={stop} />
        ) : (
          <>
            {error && <p role="alert">{error}</p>}
            {!address ? (
              <form
                onSubmit={async (e) => {
                  e.preventDefault();
                  setError("");
                  if (sats <= 0n || sats > 2100000000000000n) {
                    setError("Enter a whole number of sats above zero.");
                    return;
                  }
                  setBusy(true);
                  try {
                    const checked = await checkedAddress(
                      clanId,
                      view,
                      purpose,
                      grantId,
                    );
                    const payment = `bitcoin:${checked}?amount=${bitcoinAmount(sats)}`;
                    const image = await QRCode.toDataURL(payment, {
                      width: 320,
                      margin: 3,
                      errorCorrectionLevel: "M",
                    });
                    setQr(image);
                    setUri(payment);
                    setAddress(checked);
                  } catch (e) {
                    const message = walletMessage(e);
                    if (stopsPayment(message)) setStop(message);
                    else setError(message);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                {grant && (
                  <p>
                    Still owed: <strong>{owedLabel(grant)}</strong>
                    {owedEstimate(grant) && (
                      <small className="fine-print">
                        {" "}
                        ({owedEstimate(grant)})
                      </small>
                    )}
                  </p>
                )}
                <p>
                  Send Bitcoin to your clan wallet. You pay your wallet’s send
                  fee.
                </p>
                <p className="fine-print">
                  {view.network === "bitcoin"
                    ? "Real bitcoin. Send only what the clan agreed, to the address shown here."
                    : "Test network only. Do not send real bitcoin."}
                </p>
                {!grantId && !requestedPurpose && (
                  <label>
                    Payment for
                    <select
                      aria-label="Payment for"
                      value={purpose}
                      disabled={busy}
                      onChange={(e) =>
                        setSelectedPurpose(e.target.value as AddressPurpose)
                      }
                    >
                      <option value="contribution">My contribution</option>
                      <option value="grant_funding">Clan funding</option>
                    </select>
                  </label>
                )}
                <label>
                  Amount (sats)
                  <input
                    value={amount}
                    onChange={(e) => setAmount(e.target.value)}
                    inputMode="numeric"
                    pattern="[0-9]+"
                    required
                    maxLength={16}
                    disabled={busy}
                  />
                </label>
                {sats > 0n && <p>{money(sats)}</p>}
                {sats > 0n && sats < 5000n && (
                  <p>
                    For less than 5,000 sats, a Bitcoin send fee may be too
                    much.{" "}
                    {availableTill
                      ? "Use Lightning below instead."
                      : "Wait and send a larger amount when you can."}
                  </p>
                )}
                <button className="primary-button" disabled={busy || !amount}>
                  <Busy busy={busy}>Get payment address</Busy>
                </button>
                {grantId && grant && (
                  <button
                    type="button"
                    className="secondary-button"
                    disabled={busy}
                    onClick={() => setAgent(true)}
                  >
                    <Storefront size={20} /> Pay cash through an agent
                  </button>
                )}
              </form>
            ) : (
              <>
                <div className="payment-heading">
                  <p>
                    {grantId
                      ? "Repayment"
                      : purpose === "grant_funding"
                        ? "Clan funding"
                        : "Contribution"}
                  </p>
                  <h3>{money(sats)}</h3>
                </div>
                <p role="status" className="payment-status">
                  {confirmed ? (
                    <>
                      <CheckCircle size={22} /> Received
                    </>
                  ) : (
                    <>
                      <Hourglass size={22} /> Waiting for the network
                    </>
                  )}
                </p>
                {confirmed ? (
                  <div>
                    <p>{money(receipts.received)}</p>
                    <p>Payment received. Thank you.</p>
                  </div>
                ) : (
                  <>
                    <div className="qr-frame">
                      <img
                        className="deposit-qr"
                        src={qr}
                        width={320}
                        height={320}
                        alt={`Bitcoin payment request for ${sats} sats`}
                      />
                    </div>
                    <p className="wallet-address">{address}</p>
                    <CopyButton
                      value={address}
                      label="Copy Bitcoin address"
                      message="Bitcoin address copied"
                    />
                    <a className="primary-button" href={uri}>
                      Open Bitcoin wallet
                    </a>
                    <p>
                      In your wallet, choose Send and scan this code or paste
                      the address. Many Lightning wallets also let you send to a
                      Bitcoin address. Check your wallet’s fee before you pay.
                    </p>
                    <p className="fine-print">
                      Your balance changes after the payment is confirmed. Keep
                      this address and your wallet’s receipt. Please do not pay
                      twice while waiting.
                    </p>
                  </>
                )}
                {receipts.received > 0n && !confirmed && (
                  <div>
                    <p>{money(receipts.received)}</p>
                    <p>Received so far. You can pay a little at a time.</p>
                  </div>
                )}
                {receipts.error && (
                  <p role="alert">
                    {receipts.error} Please do not pay again while the status is
                    unclear.
                  </p>
                )}
                <button
                  className="secondary-button"
                  disabled={receipts.checking}
                  onClick={receipts.refresh}
                >
                  <Busy busy={receipts.checking}>Check payment status</Busy>
                </button>
                {receipts.payments.length > 0 && (
                  <section
                    className="wallet-flow"
                    aria-label="Payments to this address"
                  >
                    <h3>Payments to this address</h3>
                    {receipts.payments.map((r) => (
                      <div key={r.id}>
                        <p>{money(BigInt(r.amount_sats))}</p>
                        <p className="fine-print">
                          {r.status === "confirmed"
                            ? r.kes_credited_minor != null
                              ? `Received · ${kesMinor(r.kes_credited_minor)} counted`
                              : "Received"
                            : r.status === "dropped"
                              ? "No longer seen on the network. Check your wallet before sending again."
                              : r.credit_note === "waiting_for_rate"
                                ? "Confirmed. It counts in KES once today’s rate is available."
                                : `Waiting for the network · ${r.confirmations} of ${view.confirmations_required ?? 3} confirmations`}
                        </p>
                        <p className="wallet-address">
                          {r.txid.slice(0, 12)}…{r.txid.slice(-8)}
                        </p>
                      </div>
                    ))}
                  </section>
                )}
              </>
            )}
            {!address && availableTill && onLightning && (
              <button className="secondary-button" onClick={onLightning}>
                Pay with Lightning
              </button>
            )}
            {!address && tillError && (
              <>
                <p role="status" className="fine-print">
                  {tillError}
                </p>
                <button
                  className="text-button"
                  onClick={() => setReload((n) => n + 1)}
                >
                  Check Lightning again
                </button>
              </>
            )}
          </>
        )}
      </div>
    </Sheet>
  );
}
