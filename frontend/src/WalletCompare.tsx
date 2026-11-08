import { useEffect, useRef, useState } from "react";
import { WarningCircle, ShieldCheck } from "@phosphor-icons/react";
import { Sheet, Busy } from "./ui";
import { ApiError } from "./live-api";
import { vaultStore, type Protection } from "./vault-access";
import { KeyUnlock } from "./WalletKeySetup";
import {
  confirmWallet,
  getWallet,
  toClanPolicy,
  walletGeneration,
  type WalletView,
} from "./wallet-api";
import { walletCode } from "./vault/policy";
import { ownWalletKey, saveWalletCheck, walletMessage } from "./wallet-trust";
import { communityName } from "./community";
export function WalletStop({ message }: { message: string }) {
  return (
    <div className="wallet-stop" role="alert">
      <WarningCircle size={30} />
      <h3>Stop. Do not use this wallet.</h3>
      <p>{message}</p>
      <p>
        Tell your clan and contact {communityName()} before adding money or
        signing.
      </p>
    </div>
  );
}
export function WalletCompare({
  clanId,
  view,
  onClose,
  onSaved,
}: {
  clanId: string;
  view: WalletView;
  onClose: () => void;
  onSaved: (view: WalletView) => void;
}) {
  const [protection, setProtection] = useState<Protection | null>(null),
    [code, setCode] = useState(""),
    [error, setError] = useState(""),
    [stop, setStop] = useState(""),
    [busy, setBusy] = useState(false),
    [loading, setLoading] = useState(true),
    [reload, setReload] = useState(0);
  const key = useRef("");
  useEffect(() => {
    let active = true;
    setLoading(true);
    void (async () => {
      try {
        const kind = await (await vaultStore()).vaultProtection(clanId);
        if (!kind)
          throw Error(
            "There is no signing key on this phone. Restore it with your signing key backup words first.",
          );
        if (active) setProtection(kind);
      } catch (e) {
        if (active) setError(walletMessage(e));
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
      key.current = "";
    };
  }, [clanId, reload]);
  async function approve() {
    setBusy(true);
    setError("");
    try {
      const root = await getWallet(clanId);
      const fresh = walletGeneration(root, view.generation);
      if (
        !fresh.enabled ||
        !fresh.policy ||
        fresh.generation !== view.generation ||
        fresh.me.key !== key.current ||
        walletCode(toClanPolicy(fresh.policy)) !== code
      )
        throw Error("The wallet changed while you were comparing it.");
      const confirmedRoot =
        fresh.status === "active" && fresh.me.confirmed
          ? root
          : await confirmWallet(clanId, code);
      const confirmed = walletGeneration(confirmedRoot, view.generation);
      if (
        !confirmed.policy ||
        confirmed.generation !== fresh.generation ||
        confirmed.me.key !== key.current ||
        walletCode(toClanPolicy(confirmed.policy)) !== code
      )
        throw Error("The wallet changed after confirmation.");
      saveWalletCheck(clanId, confirmed, key.current, code);
      onSaved(confirmedRoot);
      onClose();
    } catch (e) {
      if (e instanceof ApiError && e.status !== 409) setError(walletMessage(e));
      else setStop(walletMessage(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Sheet
      title="Compare your wallet code"
      eyebrow="Check together"
      busy={busy}
      onClose={onClose}
    >
      <div className="wallet-flow">
        {stop ? (
          <WalletStop message={stop} />
        ) : (
          <>
            {error && <p role="alert">{error}</p>}
            {loading && <Busy busy>Checking this phone</Busy>}
            {!loading && !protection && (
              <button
                className="secondary-button"
                onClick={() => {
                  setError("");
                  setReload((n) => n + 1);
                }}
              >
                Try again
              </button>
            )}
            {protection && !code && (
              <>
                <p>
                  Unlock your signing key so this phone can check it belongs to
                  your clan.
                </p>
                <KeyUnlock
                  protection={protection}
                  busy={busy}
                  onUnlock={async (unlock) => {
                    setBusy(true);
                    setError("");
                    let opened = "",
                      unlocked = false;
                    try {
                      opened = await (
                        await vaultStore()
                      ).openVault(clanId, unlock);
                      unlocked = true;
                      key.current = ownWalletKey(opened, view);
                      setCode(walletCode(toClanPolicy(view.policy!)));
                    } catch (e) {
                      if (unlocked) setStop(walletMessage(e));
                      else setError(walletMessage(e));
                    } finally {
                      opened = "";
                      setBusy(false);
                    }
                  }}
                />
              </>
            )}
            {code && (
              <>
                <ShieldCheck size={34} />
                <div className="wallet-code" aria-label="Phone wallet code">
                  {code.slice(0, 4)} {code.slice(4)}
                </div>
                <p>
                  Compare this code with every other signatory, in person or on
                  a call. All codes must be the same.
                </p>
                <p className="fine-print">
                  This phone worked out the code itself from the clan’s public
                  signing keys.
                </p>
                <button
                  className="primary-button"
                  disabled={busy}
                  onClick={() => void approve()}
                >
                  <Busy busy={busy}>All codes match</Busy>
                </button>
                <button
                  className="secondary-button"
                  disabled={busy}
                  onClick={() =>
                    setStop(
                      "The codes are different. Do not confirm this wallet.",
                    )
                  }
                >
                  Codes are different
                </button>
              </>
            )}
          </>
        )}
      </div>
    </Sheet>
  );
}
