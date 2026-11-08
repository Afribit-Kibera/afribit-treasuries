import { useState } from "react";
import { Busy, Sheet } from "./ui";
import { ApiError } from "./live-api";
import { WalletCompare } from "./WalletCompare";
import { WalletKeySetup } from "./WalletKeySetup";
import { checkedWallet, walletMessage } from "./wallet-trust";
import {
  cancelNextWallet,
  startNextWallet,
  walletGeneration,
  type WalletView,
  type WalletStartReason,
} from "./wallet-api";
export const walletReasons: Record<WalletStartReason, string> = {
  lost_key: "Lost key",
  stolen_phone: "Stolen phone",
  signatory_change: "Signatory change",
  oversight_change: "Oversight key change",
  other: "Other",
};
// Errors from POST …/wallet/next and …/wallet/next/cancel. 409 messages come from the server.
function nextWalletMessage(e: unknown) {
  if (e instanceof ApiError) {
    if (e.status === 403)
      return "Only the clan's signatories can start or stop a new clan wallet.";
    if (e.status === 422) return "Choose why the clan needs a new wallet.";
    if (e.status === 429)
      return "The new wallet was started or stopped too many times. Try again in an hour.";
    if (e.status === 503)
      return "Clan wallets are switched off right now. Try again later.";
  }
  return walletMessage(e);
}
export function WalletNext({
  clanId,
  view,
  onSaved,
}: {
  clanId: string;
  view: WalletView;
  onSaved: (view: WalletView) => void;
}) {
  const [screen, setScreen] = useState<
    "start" | "cancel" | "key" | "compare" | null
  >(null);
  const [reason, setReason] = useState<WalletStartReason>("lost_key");
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const target = view.next
    ? walletGeneration(view, view.next.generation)
    : null;
  const signer = target?.me.is_signer ?? view.me.is_signer;
  async function change(cancel: boolean) {
    setBusy(true);
    setError("");
    try {
      onSaved(
        await (cancel
          ? cancelNextWallet(clanId)
          : startNextWallet(clanId, reason)),
      );
      setScreen(null);
    } catch (e) {
      setError(nextWalletMessage(e));
    } finally {
      setBusy(false);
    }
  }
  const open = (next: typeof screen) => {
    setError("");
    setScreen(next);
  };
  return (
    <>
      {target ? (
        <section className="wallet-flow" aria-label="New clan wallet">
          <h3>New clan wallet (generation {target.generation})</h3>
          <p>
            Started by {target.started_by || "a signatory"}
            {target.start_reason
              ? ` · ${walletReasons[target.start_reason]}`
              : ""}
            .
          </p>
          <p className="fine-print">
            Your current wallet keeps working. Every signatory sets up and
            compares the new wallet. Then the money moves across, signed like a
            payout.
          </p>
          <ul className="wallet-waiting">
            {target.signers.map((s) => (
              <li key={s.user_id}>
                <span>{s.display_name}</span>
                <span>
                  {s.confirmed
                    ? "Code checked"
                    : s.key_registered
                      ? "Key added"
                      : "Waiting"}
                </span>
              </li>
            ))}
          </ul>
          {signer && (
            <>
              <button className="secondary-button" onClick={() => open("key")}>
                {target.me.key
                  ? "Use my signing key again"
                  : "Add my signing key"}
              </button>
              {target.policy && target.me.key && (
                <button
                  className="primary-button"
                  onClick={() => open("compare")}
                >
                  Compare new wallet code
                </button>
              )}
              <button className="text-button" onClick={() => open("cancel")}>
                Stop setting up
              </button>
            </>
          )}
          {(() => {
            try {
              checkedWallet(clanId, view, target.generation);
              return (
                <p className="fine-print">
                  New wallet code checked on this phone.
                </p>
              );
            } catch {
              return null;
            }
          })()}
        </section>
      ) : (
        view.status === "active" &&
        signer && (
          <button className="secondary-button" onClick={() => open("start")}>
            Start a new clan wallet
          </button>
        )
      )}
      {view.earlier?.length > 0 && (
        <div className="wallet-flow">
          <p className="fine-print">
            Save your new wallet backup. Keep your old backup too: money sent
            late to an old address still needs it.
          </p>
          {view.earlier.map((old) => (
            <p key={old.generation}>
              Old wallet (generation {old.generation}):{" "}
              {old.balance_sats === null
                ? "checking money still to move"
                : old.balance_sats === 0
                  ? "money moved"
                  : `${old.balance_sats.toLocaleString()} sats still to move`}
            </p>
          ))}
        </div>
      )}
      {(screen === "start" || screen === "cancel") && (
        <Sheet
          title={
            screen === "start" ? "Start a new clan wallet" : "Stop setting up?"
          }
          onClose={() => setScreen(null)}
          busy={busy}
        >
          <div className="wallet-flow">
            <p>
              Your current wallet keeps working. Every signatory sets up and
              compares the new wallet. Then the money moves across, signed like
              a payout.
            </p>
            {screen === "start" ? (
              <>
                <label>
                  Why does the clan need a new wallet?
                  <select
                    value={reason}
                    onChange={(e) =>
                      setReason(e.target.value as WalletStartReason)
                    }
                    disabled={busy}
                  >
                    {Object.entries(walletReasons).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
                <p className="fine-print">
                  Enough signatories must still have their old keys to sign the
                  move. Someone who lost theirs cannot sign it.
                </p>
              </>
            ) : (
              <p>
                This stops the new wallet setup. Nothing moves. Your current
                wallet carries on.
              </p>
            )}
            {error && <p role="alert">{error}</p>}
            <button
              className="primary-button"
              disabled={busy}
              onClick={() => void change(screen === "cancel")}
            >
              <Busy busy={busy}>
                {screen === "start"
                  ? "Start wallet setup"
                  : "Yes, stop setting up"}
              </Busy>
            </button>
            <button
              className="secondary-button"
              disabled={busy}
              onClick={() => setScreen(null)}
            >
              Go back
            </button>
          </div>
        </Sheet>
      )}
      {screen === "key" && target && (
        <WalletKeySetup
          key={target.generation}
          clanId={clanId}
          network={target.network}
          generation={target.generation}
          onSaved={onSaved}
          onClose={() => setScreen(null)}
        />
      )}
      {screen === "compare" && target && (
        <WalletCompare
          key={target.generation}
          clanId={clanId}
          view={target}
          onSaved={onSaved}
          onClose={() => setScreen(null)}
        />
      )}
    </>
  );
}
