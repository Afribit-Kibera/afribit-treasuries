import { useEffect, useRef, useState } from "react";
import { ShieldCheck } from "@phosphor-icons/react";
import { Sheet, Busy } from "./ui";
import { ApiError } from "./live-api";
import { createBackupWords } from "./vault/keys";
import type { ClanNetwork } from "./vault/policy";
import { publicSigningKey } from "./wallet-trust";
import { vaultStore, type Unlock, type Protection } from "./vault-access";
import {
  getWallet,
  registerWalletKey,
  walletGeneration,
  type WalletView,
} from "./wallet-api";
import { communityName } from "./community";
export function KeyUnlock({
  protection,
  busy,
  onUnlock,
}: {
  protection: Protection;
  busy: boolean;
  onUnlock: (unlock: Unlock) => Promise<void>;
}) {
  const [pin, setPin] = useState("");
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        const unlock: Unlock =
          protection === "passkey" ? { kind: "passkey" } : { kind: "pin", pin };
        setPin("");
        void onUnlock(unlock);
      }}
    >
      {protection === "pin" && (
        <label>
          Your signing key PIN
          <input
            type="password"
            inputMode="numeric"
            pattern="[0-9]{6,12}"
            minLength={6}
            maxLength={12}
            required
            autoComplete="off"
            value={pin}
            onChange={(e) => setPin(e.target.value)}
          />
        </label>
      )}
      <button className="primary-button" disabled={busy}>
        <Busy busy={busy}>
          {protection === "passkey"
            ? "Unlock with my phone"
            : "Unlock signing key"}
        </Busy>
      </button>
    </form>
  );
}
export function KeyProtection({
  busy,
  passkey,
  onProtect,
}: {
  busy: boolean;
  passkey: boolean;
  onProtect: (unlock: Unlock) => Promise<void>;
}) {
  const [pin, setPin] = useState(""),
    [again, setAgain] = useState(""),
    [error, setError] = useState("");
  return (
    <>
      <p>
        Protect your signing key on this phone. Keep your backup words safe too.
      </p>
      {passkey && (
        <button
          className="primary-button"
          disabled={busy}
          onClick={() => void onProtect({ kind: "passkey" })}
        >
          <Busy busy={busy}>Use my phone lock</Busy>
        </button>
      )}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!/^\d{6,12}$/.test(pin) || pin !== again) {
            setError("Use the same PIN twice, with 6 to 12 digits.");
            return;
          }
          const unlock: Unlock = { kind: "pin", pin };
          setPin("");
          setAgain("");
          setError("");
          void onProtect(unlock);
        }}
      >
        <label>
          Choose a signing key PIN
          <input
            type="password"
            inputMode="numeric"
            minLength={6}
            maxLength={12}
            required
            autoComplete="new-password"
            value={pin}
            onChange={(e) => setPin(e.target.value)}
          />
        </label>
        <label>
          Enter the PIN again
          <input
            type="password"
            inputMode="numeric"
            minLength={6}
            maxLength={12}
            required
            autoComplete="new-password"
            value={again}
            onChange={(e) => setAgain(e.target.value)}
          />
        </label>
        {error && <p role="alert">{error}</p>}
        <button className="primary-button" disabled={busy}>
          <Busy busy={busy}>Protect with a PIN</Busy>
        </button>
      </form>
    </>
  );
}
function positions() {
  const result = new Set<number>();
  while (result.size < 3) {
    const n = crypto.getRandomValues(new Uint32Array(1))[0];
    if (n < 4294967292) result.add(n % 12);
  }
  return [...result].sort((a, b) => a - b);
}
export function WalletKeySetup({
  clanId,
  onClose,
  onSaved,
  generation,
  network,
}: {
  clanId: string;
  /** The wallet's network: mainnet keys differ from test-network keys. */
  network: ClanNetwork;
  onClose: () => void;
  onSaved: (view: WalletView) => void;
  generation?: number | null;
}) {
  const words = useRef(""),
    publicKey = useRef("");
  const [step, setStep] = useState<
    | "loading"
    | "why"
    | "words"
    | "check"
    | "protect"
    | "saved"
    | "unlock"
    | "reuse"
  >("loading");
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [passkey, setPasskey] = useState(false),
    [protection, setProtection] = useState<Protection>("pin");
  const [checks, setChecks] = useState<number[]>([]),
    [answers, setAnswers] = useState<string[]>(["", "", ""]);
  const [restart, setRestart] = useState(0);
  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const store = await vaultStore();
        const support = await store.vaultSupport();
        const existing = await store.vaultProtection(clanId);
        if (active) {
          setPasskey(support.passkey);
          if (existing) {
            setProtection(existing);
            setStep(generation ? "reuse" : "unlock");
          } else setStep("why");
        }
      } catch (e) {
        if (active) setError((e as Error).message);
      }
    })();
    return () => {
      active = false;
      words.current = "";
      publicKey.current = "";
    };
  }, [clanId, restart, generation]);
  async function register() {
    setBusy(true);
    setError("");
    try {
      if (!publicKey.current)
        throw Error("Unlock your saved signing key first.");
      if (generation !== undefined) {
        const root = await getWallet(clanId);
        const target = root.next || root;
        if (
          target.generation !== generation ||
          !["collecting_keys", "confirming", "not_started"].includes(
            target.status,
          )
        )
          throw Error(
            "The wallet setup changed. Close this screen and refresh the clan.",
          );
      }
      const view = await registerWalletKey(clanId, publicKey.current);
      onSaved(view);
      onClose();
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 409
          ? e.message
          : (e as Error).message,
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <Sheet
      title="Your signing key"
      eyebrow="Clan wallet"
      onClose={onClose}
      busy={busy}
    >
      <div className="wallet-flow">
        {import.meta.env.DEV && location.pathname === "/__wallet_preview" && (
          <p className="fine-print">
            Development preview: keys are kept only while this page stays open.
            Do not add real money.
          </p>
        )}
        {error && (
          <p role="alert" className="field-help">
            {error}
          </p>
        )}
        {step === "loading" && (
          <>
            <Busy busy={!error}>Checking this phone</Busy>
            {error && (
              <button
                className="secondary-button"
                onClick={() => {
                  setError("");
                  setRestart((n) => n + 1);
                }}
              >
                Try again
              </button>
            )}
          </>
        )}
        {step === "reuse" && (
          <>
            <p>
              Keep your current key if you still have it. A new key is only
              needed if yours was lost.
            </p>
            <p className="fine-print">
              This phone keeps its current key so you can still sign the move
              from the old wallet.
            </p>
            <button
              className="primary-button"
              onClick={() => setStep("unlock")}
            >
              Use my current key
            </button>
          </>
        )}
        {step === "why" && (
          <>
            <ShieldCheck size={40} />
            <p>
              You’ll hold one of the clan’s signing keys on this phone. Payouts
              need the signatories’ approval and one approver from{" "}
              {communityName()}.
            </p>
            <p>
              If you lose your phone, your backup words restore this signing
              key.
            </p>
            <button
              className="primary-button"
              onClick={() => {
                words.current = createBackupWords();
                setStep("words");
              }}
            >
              Create my signing key
            </button>
          </>
        )}
        {step === "words" && (
          <>
            <h3>Write down these 12 words</h3>
            <p>
              Write them on paper. Do not take a screenshot or share them.
              Nobody from Clans or {communityName()} will ever ask for them.
            </p>
            <p>
              <strong>
                These are different from your account recovery words.
              </strong>{" "}
              They restore your clan signing key, not your account.
            </p>
            <ol className="wallet-words">
              {words.current.split(" ").map((w, i) => (
                <li key={i}>
                  <span>{i + 1}</span> {w}
                </li>
              ))}
            </ol>
            <button
              className="primary-button"
              onClick={() => {
                setChecks(positions());
                setAnswers(["", "", ""]);
                setStep("check");
              }}
            >
              I wrote them down
            </button>
          </>
        )}
        {step === "check" && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const list = words.current.split(" ");
              if (
                checks.some(
                  (pos, i) => answers[i].trim().toLowerCase() !== list[pos],
                )
              ) {
                setAnswers(["", "", ""]);
                setError(
                  "Those words did not match. Check your written copy and try again.",
                );
                setStep("words");
                return;
              }
              setAnswers(["", "", ""]);
              setError("");
              setStep("protect");
            }}
          >
            <p>Check your written copy.</p>
            {checks.map((pos, i) => (
              <label key={pos}>
                Word {pos + 1}
                <input
                  type="password"
                  required
                  autoComplete="off"
                  spellCheck={false}
                  autoCapitalize="none"
                  value={answers[i]}
                  onChange={(e) =>
                    setAnswers((old) =>
                      old.map((v, n) => (n === i ? e.target.value : v)),
                    )
                  }
                />
              </label>
            ))}
            <button className="primary-button">Check my words</button>
          </form>
        )}
        {step === "protect" && (
          <KeyProtection
            busy={busy}
            passkey={passkey}
            onProtect={async (unlock) => {
              setBusy(true);
              setError("");
              try {
                const store = await vaultStore();
                if (await store.vaultProtection(clanId))
                  throw Error(
                    "This phone already has a signing key. Keep it and use your current key for setup.",
                  );
                await store.saveVault(clanId, words.current, unlock);
                publicKey.current = publicSigningKey(words.current, network);
                words.current = "";
                setStep("saved");
              } catch (e) {
                setError((e as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          />
        )}
        {step === "unlock" && (
          <>
            <p>
              A signing key is already saved on this phone. Unlock it to
              continue setup.
            </p>
            <KeyUnlock
              protection={protection}
              busy={busy}
              onUnlock={async (unlock) => {
                setBusy(true);
                setError("");
                let opened = "";
                try {
                  opened = await (await vaultStore()).openVault(clanId, unlock);
                  publicKey.current = publicSigningKey(opened, network);
                  setStep("saved");
                } catch (e) {
                  setError((e as Error).message);
                } finally {
                  opened = "";
                  setBusy(false);
                }
              }}
            />
          </>
        )}
        {step === "saved" && (
          <>
            <p>
              Your signing key is saved on this phone. Only its public part is
              sent to your clan.
            </p>
            <button
              className="primary-button"
              disabled={busy}
              onClick={() => void register()}
            >
              <Busy busy={busy}>Add my signing key</Busy>
            </button>
            {error && (
              <>
                <button
                  className="secondary-button"
                  disabled={busy}
                  onClick={async () => {
                    setBusy(true);
                    try {
                      const root = await getWallet(clanId);
                      const fresh =
                        generation === undefined
                          ? root
                          : walletGeneration(root, generation);
                      if (await (await vaultStore()).vaultProtection(clanId))
                        throw Error(
                          "Keep the signing key already saved on this phone. Close setup and use your current key.",
                        );
                      if (
                        !fresh.enabled ||
                        fresh.me.key ||
                        !["not_started", "collecting_keys"].includes(
                          fresh.status,
                        )
                      )
                        throw Error(
                          "Your clan already has a key for you. Go back and restore that signing key instead.",
                        );
                      publicKey.current = "";
                      setError("");
                      setStep("why");
                    } catch (e) {
                      setError((e as Error).message);
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  Start again
                </button>
                <button className="secondary-button" onClick={onClose}>
                  Back to my clan
                </button>
              </>
            )}
          </>
        )}
      </div>
    </Sheet>
  );
}
