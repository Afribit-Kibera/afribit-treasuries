import { useState } from "react";
import type { Grant } from "./live-api";
import { networkLabel, type WalletView } from "./wallet-api";
import { owedEstimate, owedLabel } from "./grant-debt";
import { WalletPayout } from "./WalletPayout";
import { BeneficiaryAddress } from "./BeneficiaryAddress";
export { BeneficiaryAddress } from "./BeneficiaryAddress";
export function WalletGrantMoney({
  clanId,
  grant,
  view,
  isBeneficiary,
  onRepay,
  onCheckWallet,
  onRefresh,
}: {
  clanId: string;
  grant: Grant;
  view: WalletView;
  isBeneficiary: boolean;
  // Lightning's switches. Clan wallet payments don't use Lightning, so they're ignored here.
  receivingEnabled: boolean;
  payoutsEnabled: boolean;
  onRepay: () => void;
  onCheckWallet?: () => void;
  onRefresh?: () => Promise<unknown>;
}) {
  const [revision, setRevision] = useState(0);
  return (
    <div className="wallet-flow">
      <p className="fine-print">{networkLabel(view.network)} · Clan wallet</p>
      {isBeneficiary &&
        grant.accepted_at &&
        ["awaiting_funding", "awaiting_signatures"].includes(grant.status) && (
          <BeneficiaryAddress
            clanId={clanId}
            network={view.network}
            grant={grant}
            onSaved={async () => {
              setRevision((n) => n + 1);
              await onRefresh?.();
            }}
          />
        )}
      {grant.accepted_at ? (
        <WalletPayout
          key={revision}
          clanId={clanId}
          grantId={grant.id}
          view={view}
          onCheckWallet={onCheckWallet}
          isBeneficiary={isBeneficiary}
          onRefresh={onRefresh}
        />
      ) : (
        <p>
          The member must accept the grant before a payment can be prepared.
        </p>
      )}
      {isBeneficiary &&
        grant.status === "in_recovery" &&
        BigInt(grant.outstanding_msat) > 0n && (
          <>
            <p>
              Still owed: <strong>{owedLabel(grant)}</strong>
              {owedEstimate(grant) && (
                <small className="fine-print"> ({owedEstimate(grant)})</small>
              )}
            </p>
            <button className="primary-button" onClick={onRepay}>
              Repay this grant
            </button>
          </>
        )}
    </div>
  );
}
