import { useEffect, useRef, useState } from "react";
import { Check, Copy } from "@phosphor-icons/react";

export function CopyButton({
  value,
  label = "Copy invoice",
  disabled = false,
  message = "Copied",
}: {
  value: string;
  label?: string;
  disabled?: boolean;
  message?: string;
}) {
  const [copied, setCopied] = useState(false);
  const [manual, setManual] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);
  useEffect(() => { setCopied(false); setManual(false); clearTimeout(timer.current); }, [value]);
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setManual(false);
      clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), 3500);
    } catch {
      setManual(true);
    }
  }
  return (
    <div className="copy-action">
      <button
        type="button"
        className={`secondary-button copy-button ${copied ? "is-copied" : ""}`}
        disabled={disabled}
        onClick={() => void copy()}
      >
        {copied ? <Check size={21} weight="bold" /> : <Copy size={21} />}
        {copied ? "Copied" : label}
      </button>
      {copied && (
        <div role="status" className="copy-toast">
          <Check size={19} />
          {message}
        </div>
      )}
      {manual && (
        <div className="copy-fallback">
          <p role="status">
            Copy was blocked. Press and hold the text below to copy it.
          </p>
          <textarea
            readOnly
            aria-label="Text to copy"
            value={value}
            onFocus={(event) => event.currentTarget.select()}
            rows={3}
          />
        </div>
      )}
    </div>
  );
}
