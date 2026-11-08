import { useState, type FormEvent } from "react";
import { ArrowLeft, Phone } from "@phosphor-icons/react";
import { call, isCode, isReason } from "./core";
import type { Registered, WalletToRegister } from "./types";
import { useApp } from "./state";
import { Busy, Notice, PageHeading, Problem, useFocusHeading } from "./ui";

/**
 * Register one clan wallet after a signatory reads its 8-character wallet code by phone.
 * Two tries, as in the console: the first mismatch asks them to read it again.
 */
export function RegisterWallet({
  wallet,
  onDone,
  doneLabel,
  onCancel,
  eyebrow = "Register a clan wallet",
}: {
  wallet: WalletToRegister;
  onDone: () => void;
  doneLabel: string;
  onCancel: () => void;
  eyebrow?: string;
}) {
  const app = useApp();
  const [code, setCode] = useState("");
  const [tries, setTries] = useState(0);
  const [retry, setRetry] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [locked, setLocked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<Registered | null>(null);
  const name = wallet.clan_name || `Clan ${wallet.clan_id}`;
  useFocusHeading(`register-${wallet.clan_id}-${wallet.generation}`);

  const typed = code.replace(/[\s-]/g, "");

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || locked || !typed) return;
    setBusy(true);
    setError(null);
    setRetry(false);
    try {
      const result = await call("register_wallet", {
        clan_id: wallet.clan_id,
        generation: wallet.generation,
        code,
      });
      setDone(result);
      app.changed();
      void app.reloadClans().catch(() => undefined);
    } catch (reason) {
      const mismatch = isReason(reason, "code_mismatch");
      if (mismatch && tries === 0) {
        setRetry(true);
        setCode("");
      } else {
        setError(reason);
        setLocked(isCode(reason, "check"));
      }
      setTries(tries + 1);
    } finally {
      setBusy(false);
    }
  }

  if (done)
    return (
      <div className="screen narrow">
        <PageHeading eyebrow={eyebrow} title={`${done.clan_name || name} is registered`} />
        <Notice tone="good" title="Registered.">
          <p>
            {done.clan_name || name} needs {done.threshold} of {done.signers} signatories.
          </p>
        </Notice>
        <div className="actions actions-end">
          <button className="primary-button" onClick={onDone} autoFocus>
            {doneLabel}
          </button>
        </div>
      </div>
    );

  return (
    <div className="screen narrow">
      <PageHeading eyebrow={eyebrow} title={`New clan wallet: ${name}`} />
      {wallet.generation > 1 && (
        <p className="lead">The clan has moved to a new wallet (wallet {wallet.generation}).</p>
      )}
      <ol className="phone-steps">
        <li>
          <Phone size={20} aria-hidden /> Phone one of the clan's signatories.
        </li>
        <li>Ask them to open Clans and go to the clan wallet.</li>
        <li>Ask them to read you the 8-character wallet code.</li>
      </ol>

      {retry && (
        <Notice tone="warning" title="That code doesn't match.">
          <p>Ask them to read it again, slowly.</p>
        </Notice>
      )}
      {error !== null && (
        <Problem error={error}>
          {locked && <p>Not registered. Nothing was signed.</p>}
        </Problem>
      )}

      <form onSubmit={(event) => void submit(event)} className="card">
        <div className="field">
          <label htmlFor="wallet-code">Wallet code they read</label>
          <input
            id="wallet-code"
            className="code-input"
            value={code}
            maxLength={40}
            autoComplete="off"
            autoCapitalize="off"
            autoCorrect="off"
            spellCheck={false}
            autoFocus
            disabled={locked || busy}
            onChange={(event) => setCode(event.target.value)}
          />
          <p className="field-hint">
            Spaces and dashes don't matter. {typed.length > 0 && `${typed.length} of 8 characters.`}
          </p>
        </div>
        <div className="actions">
          <button type="button" className="secondary-button" onClick={onCancel} disabled={busy}>
            <ArrowLeft size={18} aria-hidden /> {locked ? "Back" : "Do this later"}
          </button>
          <button className="primary-button" disabled={busy || locked || !typed}>
            <Busy busy={busy}>Register this wallet</Busy>
          </button>
        </div>
      </form>
    </div>
  );
}
