import { useState } from "react";
import { CopyButton } from "./CopyButton";

type WalletProvider = {
  enable(): Promise<void>;
  sendPayment(invoice: string): Promise<unknown>;
};

export function WalletChooser({
  invoice,
  onPaymentSubmitted,
}: {
  invoice: string;
  onPaymentSubmitted?: () => void;
}) {
  const [wallet, setWallet] = useState("any");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const provider = (window as Window & { webln?: WalletProvider }).webln;
  async function payHere() {
    if (!provider) return;
    setBusy(true);
    setMessage("");
    try {
      await provider.enable();
      await provider.sendPayment(invoice);
      setMessage("Payment sent. Checking that your clan received it.");
      onPaymentSubmitted?.();
    } catch {
      setMessage(
        "Payment was not confirmed here. Check your wallet before trying again.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="wallet-chooser" aria-label="Choose how to pay">
      <label>
        Pay with
        <select
          value={wallet}
          onChange={(event) => setWallet(event.target.value)}
        >
          <option value="any">My Lightning wallet</option>
          <option value="blink">Blink</option>
          <option value="fedi">Fedi</option>
        </select>
      </label>
      {provider && wallet !== "blink" && (
        <button
          className="primary-button"
          disabled={busy}
          onClick={() => void payHere()}
        >
          {busy ? "Opening payment..." : "Pay in this wallet"}
        </button>
      )}
      <a
        className="primary-button"
        href={
          wallet === "blink" ? `blink://${invoice}` : `lightning:${invoice}`
        }
      >
        {wallet === "blink" ? "Open Blink" : "Open a wallet"}
      </a>
      <p className="wallet-help">
        {wallet === "blink"
          ? "This opens Blink if it is installed. If it does not open, copy the request and paste it under Send in Blink."
          : wallet === "fedi"
            ? "Your phone chooses the app for this link. To use Fedi, open this page inside Fedi or copy the request and paste it under Send there."
            : "Your phone chooses which wallet opens. You can also copy the request and paste it in your wallet."}
      </p>
      <CopyButton
        value={invoice}
        label="Copy payment request"
        message="Copied. Open your wallet and paste it under Send."
      />
      {message && <p role="status">{message}</p>}
    </section>
  );
}
