import { useState } from "react";
import { ShieldCheck } from "@phosphor-icons/react";
import { useClanWallet } from "./useClanWallet";
import { WalletKeySetup } from "./WalletKeySetup";
import { WalletCompare } from "./WalletCompare";
import { WalletRestore } from "./WalletRestore";
import { checkedWallet } from "./wallet-trust";
import { WalletBackup } from "./WalletBackup";
import { WalletNext } from "./WalletNext";
import { WalletMaintenance } from "./WalletMaintenance";
import { WalletAlarms } from "./WalletAlarms";
import { communityName } from "./community";
import { networkLabel } from "./wallet-api";
export function WalletCard({
  clanId,
  clanName,
}: {
  clanId: string;
  clanName: string;
}) {
  const { view, refresh, setView, error, loading } = useClanWallet(clanId);
  const [setup, setSetup] = useState(false);
  const [compare, setCompare] = useState(false);
  const [restore, setRestore] = useState(false);
  if (!view?.enabled) return null;
  return (
    <section className="wallet-card" aria-label="Clan wallet">
      <div className="section-header">
        <h3>
          <ShieldCheck size={24} /> Clan wallet
        </h3>
        <span className="count-label">{networkLabel(view.network)}</span>
      </div>
      <WalletAlarms clanId={clanId} view={view} />
      <p>
        {
          {
            not_started: "Not started",
            collecting_keys: "Waiting for signing keys",
            confirming: "Compare the wallet code",
            active: "Clan wallet ready",
            retired: "Previous clan wallet",
          }[view.status]
        }
      </p>
      <p className="fine-print">
        {view.signers.filter((s) => s.key_registered).length} of{" "}
        {view.signer_count} keys added ·{" "}
        {view.signers.filter((s) => s.confirmed).length} of {view.signer_count}{" "}
        confirmed
      </p>
      {view.status === "active" && (
        <>
          <p>
            Payouts need {view.threshold} of {view.signer_count} signatories and
            one approver from {communityName()}.
          </p>
          <p className="fine-print">
            If {communityName()} cannot sign, {view.recovery_threshold} signatories can
            recover eligible money after {view.recovery_days} days. The wait
            counts separately for each payment into the wallet.
          </p>
        </>
      )}
      {view.me.is_signer &&
        !view.me.key &&
        ["not_started", "collecting_keys"].includes(view.status) && (
          <button className="primary-button" onClick={() => setSetup(true)}>
            Create my signing key
          </button>
        )}
      <ul className="wallet-waiting">
        {view.signers.map((s) => (
          <li key={s.user_id}>
            <span>{s.display_name}</span>
            <span>{s.key_registered ? "Key added" : "Waiting"}</span>
          </li>
        ))}
      </ul>
      {view.me.is_signer &&
        view.me.key &&
        ["confirming", "active"].includes(view.status) && (
          <button className="primary-button" onClick={() => setCompare(true)}>
            {view.me.confirmed
              ? "Check wallet code on this phone"
              : "Compare wallet code"}
          </button>
        )}
      {view.me.confirmed &&
        (() => {
          try {
            checkedWallet(clanId, view);
            return (
              <p className="fine-print">Wallet code checked on this phone.</p>
            );
          } catch {
            return null;
          }
        })()}
      <WalletBackup clanId={clanId} clanName={clanName} view={view} />
      <WalletNext clanId={clanId} view={view} onSaved={setView} />
      {view.status === "active" && (
        <WalletMaintenance
          clanId={clanId}
          view={view}
          onRefresh={refresh}
        />
      )}
      {view.me.is_signer &&
        view.me.key &&
        ["collecting_keys", "confirming", "active"].includes(view.status) && (
          <button className="secondary-button" onClick={() => setRestore(true)}>
            I have a new phone
          </button>
        )}
      {error && <p role="alert">{error}</p>}
      <button
        className="secondary-button"
        disabled={loading}
        onClick={() => void refresh()}
      >
        Refresh wallet
      </button>
      {setup && (
        <WalletKeySetup
          clanId={clanId}
          network={view.network}
          onClose={() => setSetup(false)}
          onSaved={setView}
        />
      )}
      {compare && (
        <WalletCompare
          clanId={clanId}
          view={view}
          onClose={() => setCompare(false)}
          onSaved={setView}
        />
      )}
      {restore && (
        <WalletRestore
          clanId={clanId}
          view={view}
          onClose={() => setRestore(false)}
          onRestored={() => {
            setRestore(false);
            if (["confirming", "active"].includes(view.status))
              setCompare(true);
          }}
        />
      )}
    </section>
  );
}
