import { useState } from "react";
import { ApiError, type Grant } from "./live-api";
import { Busy } from "./ui";
import { useWalletMoney } from "./WalletMoney";
import { WalletStop } from "./WalletCompare";
import {
  getPayoutQuote,
  safeSats,
  setPayoutAddress,
  validatePayoutAddress,
  type PayoutPreview,
} from "./wallet-api";
import { walletMessage } from "./wallet-trust";
import type { ClanNetwork } from "./vault/policy";

function checkQuote(
  quote: PayoutPreview,
  address: string,
  approvedSats: number,
) {
  const approved = safeSats(quote.approved_sats),
    fee = safeSats(quote.estimated_fee_sats),
    received = safeSats(quote.estimated_received_sats);
  if (
    quote.address !== address ||
    approved !== safeSats(approvedSats) ||
    quote.fee_paid_by !== "recipients" ||
    received !== approved - fee ||
    received < 1000n ||
    !Number.isFinite(quote.fee_rate_sat_vb) ||
    quote.fee_rate_sat_vb <= 0
  )
    throw Error(
      "The payment estimate does not match your grant. Do not use it.",
    );
}
function requestMessage(error: unknown) {
  if (error instanceof ApiError && error.status === 503)
    return "The Bitcoin network cannot be checked right now. Please try again in a moment.";
  const message = walletMessage(error);
  return message.includes("enough confirmed money")
    ? message + " Wait for the clan’s deposits to confirm, then try again."
    : message;
}
export function BeneficiaryAddress({
  clanId,
  grant,
  onSaved,
  network,
}: {
  clanId: string;
  network: ClanNetwork;
  grant: Grant;
  onSaved?: () => Promise<unknown>;
}) {
  const [address, setAddress] = useState(""),
    [preview, setPreview] = useState<PayoutPreview | null>(null),
    [saved, setSaved] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [stop, setStop] = useState("");
  const money = useWalletMoney();
  async function quote() {
    setError("");
    let checked = "";
    try {
      checked = validatePayoutAddress(address, network);
    } catch (e) {
      setError(walletMessage(e));
      return;
    }
    setBusy(true);
    try {
      const next = await getPayoutQuote(clanId, grant.id, checked);
      checkQuote(next, checked, grant.amount_sats);
      setPreview(next);
      setSaved(false);
    } catch (e) {
      if (walletMessage(e).includes("estimate does not match"))
        setStop(walletMessage(e));
      else setError(requestMessage(e));
    } finally {
      setBusy(false);
    }
  }
  async function confirm() {
    if (!preview || saved) return;
    setError("");
    setBusy(true);
    try {
      const next = await setPayoutAddress(clanId, grant.id, preview.address);
      checkQuote(next, preview.address, grant.amount_sats);
      if (
        next.estimated_fee_sats !== preview.estimated_fee_sats ||
        next.fee_rate_sat_vb !== preview.fee_rate_sat_vb
      ) {
        setError(
          "Your address was added, and the estimated fee changed. Check the new amount below. Your signatories must check the final payment too.",
        );
      }
      setPreview(next);
      setSaved(true);
      try {
        await onSaved?.();
      } catch {
        setError(
          "Your address was saved. The grant could not be refreshed yet. Open the grant again to check its progress.",
        );
      }
    } catch (e) {
      if (walletMessage(e).includes("estimate does not match"))
        setStop(walletMessage(e));
      else setError(requestMessage(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="wallet-flow">
      <h3>Your Bitcoin receiving address</h3>
      {stop ? (
        <WalletStop message={stop} />
      ) : (
        <>
          {error && <p role="alert">{error}</p>}
          {!preview ? (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void quote();
              }}
            >
              <p>
                Paste a Bitcoin address from your wallet. Look under Receive,
                then Bitcoin address.
                {network !== "bitcoin" && " Use a test-network wallet for now."}
              </p>
              <label>
                Bitcoin address
                <input
                  value={address}
                  onChange={(e) => {
                    setAddress(e.target.value);
                    setError("");
                  }}
                  required
                  maxLength={150}
                  disabled={busy}
                  autoCapitalize="none"
                  autoComplete="off"
                  spellCheck={false}
                />
              </label>
              <dl className="wallet-amounts">
                <dt>Approved amount</dt>
                <dd>{money(safeSats(grant.amount_sats))}</dd>
              </dl>
              <p>
                The network fee comes out of your grant. Check the estimate
                before you add your address. Some Lightning wallets also charge
                a small fee to bring Bitcoin payments into your balance.
              </p>
              <button
                className="primary-button"
                disabled={busy || !address.trim()}
              >
                <Busy busy={busy}>Check receiving amount</Busy>
              </button>
            </form>
          ) : (
            <>
              <p>
                {saved
                  ? "Address added. Your signatories still need to check and sign the payment."
                  : "Check the amount and address before you continue. Your address has not been added yet."}
              </p>
              <p className="wallet-address">{preview.address}</p>
              <dl className="wallet-amounts">
                <dt>Approved amount</dt>
                <dd>{money(safeSats(preview.approved_sats))}</dd>
                <dt>Estimated network fee</dt>
                <dd>{money(safeSats(preview.estimated_fee_sats))}</dd>
                <dt>You’ll receive about</dt>
                <dd>{money(safeSats(preview.estimated_received_sats))}</dd>
              </dl>
              <p className="fine-print">
                You pay this network fee from the grant. The final fee is
                checked before anyone signs.
              </p>
              {!saved && (
                <button
                  className="primary-button"
                  disabled={busy}
                  onClick={() => void confirm()}
                >
                  <Busy busy={busy}>Use this Bitcoin address</Busy>
                </button>
              )}
              <button
                className="secondary-button"
                disabled={busy}
                onClick={() => {
                  setPreview(null);
                  setSaved(false);
                  setError("");
                }}
              >
                Use another address
              </button>
              {saved && (
                <p className="fine-print">
                  Changing your address before payment goes out means the
                  signatories must sign the new payment.
                </p>
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}
