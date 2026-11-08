import { useEffect, useRef, useState } from "react";
import { wordlist } from "@scure/bip39/wordlists/english.js";
import { Sheet, Busy } from "./ui";
import { KeyProtection } from "./WalletKeySetup";
import { vaultStore, type Unlock } from "./vault-access";
import {
  publicSigningKey,
  requireWalletRecheck,
  walletMessage,
} from "./wallet-trust";
import type { WalletView } from "./wallet-api";
export function WalletRestore({
  clanId,
  view,
  onClose,
  onRestored,
}: {
  clanId: string;
  view: WalletView;
  onClose: () => void;
  onRestored: () => void;
}) {
  const [entries, setEntries] = useState(() => Array<string>(12).fill("")),
    [focused, setFocused] = useState(-1),
    [step, setStep] = useState<"words" | "protect" | "saved">("words"),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [passkey, setPasskey] = useState(false);
  const words = useRef("");
  useEffect(
    () => () => {
      words.current = "";
    },
    [],
  );
  const suggestions =
    focused >= 0 &&
    entries[focused].length >= 2 &&
    !wordlist.includes(entries[focused])
      ? wordlist
          .filter((w) => w.startsWith(entries[focused].toLowerCase()))
          .slice(0, 6)
      : [];
  async function protect(unlock: Unlock) {
    setBusy(true);
    setError("");
    try {
      if (!words.current) throw Error("Enter your backup words again.");
      if (publicSigningKey(words.current, view.network) !== view.me.key)
        throw Error("These words are for a different key.");
      if (view.earlier.some(old => old.balance_sats !== 0) && await (await vaultStore()).vaultProtection(clanId))
        throw Error("Keep this phone's current signing key until the old wallet's money has moved. Restore a different key on a new phone.");
      requireWalletRecheck(clanId, view.generation);
      await (await vaultStore()).saveVault(clanId, words.current, unlock);
      words.current = "";
      setStep("saved");
    } catch (e) {
      setError(walletMessage(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Sheet
      title="Restore your signing key"
      eyebrow="New phone"
      busy={busy}
      onClose={onClose}
    >
      <div className="wallet-flow">
        {error && <p role="alert">{error}</p>}
        {step === "words" && (
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              setBusy(true);
              setError("");
              try {
                if (
                  entries.some(
                    (w) => !wordlist.includes(w.trim().toLowerCase()),
                  )
                )
                  throw Error("Enter one valid backup word in each box.");
                const entered = entries
                  .map((w) => w.trim().toLowerCase())
                  .join(" ");
                if (publicSigningKey(entered, view.network) !== view.me.key)
                  throw Error("These words are for a different key.");
                const support = await (await vaultStore()).vaultSupport();
                words.current = entered;
                setPasskey(support.passkey);
                setEntries(Array(12).fill(""));
                setFocused(-1);
                setStep("protect");
              } catch (e) {
                setError(walletMessage(e));
              } finally {
                setBusy(false);
              }
            }}
            autoComplete="off"
          >
            <p>
              Enter the 12 words you wrote down for this clan’s signing key.
              These are different from your account recovery words. They stay on
              this phone.
            </p>
            <div className="wallet-restore">
              {entries.map((value, i) => (
                <label key={i}>
                  Word {i + 1}
                  <input
                    type="password"
                    value={value}
                    onChange={(e) =>
                      setEntries((old) =>
                        old.map((w, n) =>
                          n === i ? e.target.value.trim().toLowerCase() : w,
                        ),
                      )
                    }
                    onFocus={() => setFocused(i)}
                    autoComplete="off"
                    autoCapitalize="none"
                    spellCheck={false}
                    required
                    maxLength={12}
                    disabled={busy}
                    aria-autocomplete="list"
                    aria-controls={
                      focused === i && suggestions.length
                        ? "wallet-word-suggestions"
                        : undefined
                    }
                  />
                  {focused === i && suggestions.length > 0 && (
                    <div
                      id="wallet-word-suggestions"
                      role="listbox"
                      aria-label={`Word ${i + 1} suggestions`}
                    >
                      {suggestions.map((w) => (
                        <button
                          key={w}
                          type="button"
                          role="option"
                          aria-selected="false"
                          className="text-button"
                          onMouseDown={(e) => e.preventDefault()}
                          onClick={() =>
                            setEntries((old) =>
                              old.map((v, n) => (n === i ? w : v)),
                            )
                          }
                        >
                          {w}
                        </button>
                      ))}
                    </div>
                  )}
                </label>
              ))}
            </div>
            <button className="primary-button" disabled={busy}>
              <Busy busy={busy}>Check backup words</Busy>
            </button>
          </form>
        )}
        {step === "protect" && (
          <KeyProtection passkey={passkey} busy={busy} onProtect={protect} />
        )}
        {step === "saved" && (
          <>
            <h3>Signing key restored</h3>
            <p>
              {view.policy
                ? "Before you sign a payment, compare the wallet code with the other signatories again."
                : "Your clan is still collecting signing keys. Compare the wallet code together when everyone is ready."}
            </p>
            <button className="primary-button" onClick={onRestored}>
              {view.policy ? "Compare wallet code" : "Done"}
            </button>
          </>
        )}
      </div>
    </Sheet>
  );
}
