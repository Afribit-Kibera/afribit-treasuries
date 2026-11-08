import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { Check, Copy, Eye, EyeSlash, Info, WarningCircle } from "@phosphor-icons/react";
// Shared with the phone app: the spinner used inside busy buttons.
import { Busy } from "../../frontend/src/ui.tsx";
import { CoreError, problemText } from "./core";
import type { CheckedAddress } from "./types";

export { Busy };

const number = new Intl.NumberFormat("en-KE");

export const sats = (value: number) => `${number.format(value)} sats`;
export const plural = (count: number, one: string, many = `${one}s`) =>
  `${count} ${count === 1 ? one : many}`;

/** The core sends UTC. A time without a zone is read as UTC too. */
export function parseTime(raw: string | null | undefined): Date | null {
  if (!raw) return null;
  const zoned = /(Z|[+-]\d\d:?\d\d)$/i.test(raw) || !raw.includes("T") ? raw : `${raw}Z`;
  const at = new Date(zoned);
  return Number.isFinite(at.getTime()) ? at : null;
}

export function when(raw: string | null | undefined) {
  const at = parseTime(raw);
  return at
    ? at.toLocaleString("en-GB", {
        day: "numeric",
        month: "short",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "Time unknown";
}

export const clock = (at: Date) =>
  at.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });

export function kindLabel(kind: string) {
  if (kind === "grant") return "Grant";
  if (kind === "refresh") return "Refresh";
  if (kind === "move") return "Move to a new wallet";
  return kind;
}

export function networkLabel(network: string) {
  return network === "bitcoin" ? "Bitcoin mainnet" : "Test network";
}

/** A failed core call, shown calmly. Technical detail sits behind a toggle for the team. */
export function Problem({ error, children }: { error: unknown; children?: ReactNode }) {
  const technical = error instanceof CoreError && error.code !== "check";
  return (
    <div className="problem" role="alert">
      <WarningCircle size={22} aria-hidden />
      <div>
        <p>{problemText(error)}</p>
        {children}
        {technical && (
          <details className="details">
            <summary>Details for the team</summary>
            <p>
              {(error as CoreError).code}: {(error as CoreError).message}
            </p>
          </details>
        )}
      </div>
    </div>
  );
}

export function Notice({
  tone = "info",
  title,
  children,
}: {
  tone?: "info" | "warning" | "good";
  title?: string;
  children?: ReactNode;
}) {
  const Icon = tone === "good" ? Check : tone === "warning" ? WarningCircle : Info;
  return (
    <div className={`notice notice-${tone}`} role={tone === "warning" ? "alert" : "status"}>
      <Icon size={22} weight={tone === "good" ? "bold" : "regular"} aria-hidden />
      <div>
        {title && <strong>{title}</strong>}
        {children}
      </div>
    </div>
  );
}

export function CopyButton({ value, label = "Copy" }: { value: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  const [blocked, setBlocked] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);
  useEffect(() => {
    setCopied(false);
    setBlocked(false);
  }, [value]);
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setBlocked(false);
      clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), 3500);
    } catch {
      setBlocked(true);
    }
  }
  return (
    <span className="copy">
      <button
        type="button"
        className={`secondary-button ${copied ? "is-copied" : ""}`}
        onClick={() => void copy()}
      >
        {copied ? <Check size={19} weight="bold" aria-hidden /> : <Copy size={19} aria-hidden />}
        {copied ? "Copied" : label}
      </button>
      <span role="status" className="copy-status">
        {blocked ? "Copy was blocked. Select the text and press Ctrl+C." : ""}
      </span>
    </span>
  );
}

/**
 * An address with the characters read back by phone emphasised: the fixed start, then the
 * 6 characters after it, the middle, and the last 6.
 */
export function Address({ value, large = false }: { value: CheckedAddress; large?: boolean }) {
  const { address, fixed_start, check_start, check_end } = value;
  const head = fixed_start.length;
  const fits =
    address.startsWith(fixed_start + check_start) &&
    address.endsWith(check_end) &&
    address.length >= head + check_start.length + check_end.length;
  const className = `address ${large ? "address-large" : ""}`;
  if (!fits) return <code className={className}>{address}</code>;
  const middle = address.slice(head + check_start.length, address.length - check_end.length);
  const chunks = middle.match(/.{1,4}/g) || [];
  return (
    <code className={className} aria-label={address}>
      <span className="address-fixed">{fixed_start}</span>
      <mark>{check_start}</mark>
      {chunks.map((chunk, index) => (
        <span className="address-chunk" key={index}>
          {chunk}
        </span>
      ))}
      <mark>{check_end}</mark>
    </code>
  );
}

/** Password box with show/hide and a caps-lock warning. Nothing here keeps the value. */
export function PassphraseField({
  label,
  value,
  onChange,
  autoFocus = false,
  hint,
  disabled = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  autoFocus?: boolean;
  hint?: ReactNode;
  disabled?: boolean;
}) {
  const id = useId();
  const [shown, setShown] = useState(false);
  const [caps, setCaps] = useState(false);
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <div className="passphrase">
        <input
          id={id}
          type={shown ? "text" : "password"}
          value={value}
          autoComplete="off"
          autoCapitalize="off"
          autoCorrect="off"
          spellCheck={false}
          autoFocus={autoFocus}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
          onKeyUp={(event) => setCaps(event.getModifierState("CapsLock"))}
          onKeyDown={(event) => setCaps(event.getModifierState("CapsLock"))}
          aria-describedby={`${id}-hint`}
        />
        <button
          type="button"
          className="eye-button"
          aria-label={shown ? "Hide what you typed" : "Show what you typed"}
          aria-pressed={shown}
          onClick={() => setShown(!shown)}
          disabled={disabled}
        >
          {shown ? <EyeSlash size={20} /> : <Eye size={20} />}
        </button>
      </div>
      <p className="field-hint" id={`${id}-hint`}>
        {caps && <span className="caps">Caps Lock is on. </span>}
        {hint}
      </p>
    </div>
  );
}

export function PageHeading({
  eyebrow,
  title,
  children,
}: {
  eyebrow?: string;
  title: string;
  children?: ReactNode;
}) {
  return (
    <header className="page-heading">
      <div>
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h1 tabIndex={-1}>{title}</h1>
      </div>
      {children && <div className="page-heading-actions">{children}</div>}
    </header>
  );
}

/** Moves focus to the screen's heading when it opens, for keyboard and screen-reader use. */
export function useFocusHeading(key: unknown) {
  useEffect(() => {
    const heading = document.querySelector<HTMLElement>("main h1");
    heading?.focus({ preventScroll: false });
  }, [key]);
}
