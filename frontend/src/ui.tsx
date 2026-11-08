import {
  createContext,
  useContext,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  type ReactNode,
} from "react";
import { X, CircleNotch } from "@phosphor-icons/react";
export const FeedbackContext = createContext("");

export function useScreenStart(screen: unknown) {
  useLayoutEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "instant" });
  }, [screen]);
}

export function Avatar({
  name,
  small = false,
}: {
  name: string;
  small?: boolean;
}) {
  return (
    <span className={`avatar ${small ? "avatar-small" : ""}`} aria-label={name}>
      {name
        .split(" ")
        .map((part) => part[0])
        .slice(0, 2)
        .join("")}
    </span>
  );
}

export function Sheet({
  title,
  eyebrow,
  children,
  onClose,
  busy = false,
}: {
  title: string;
  eyebrow?: string;
  children: ReactNode;
  onClose: () => void;
  busy?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const headingId = useId();
  const error = useContext(FeedbackContext);
  const closing = useRef(false);
  function dismiss() {
    if (busy || closing.current) return;
    closing.current = true;
    if (
      matchMedia("(prefers-reduced-motion: reduce)").matches ||
      !ref.current?.animate
    ) {
      onClose();
      return;
    }
    const content =
      ref.current.querySelector<HTMLElement>(".sheet-inner") || ref.current;
    const animation = content.animate(
      [
        { opacity: 1, transform: "translateY(0)" },
        { opacity: 0, transform: "translateY(20px)" },
      ],
      { duration: 160, easing: "ease-in", fill: "forwards" },
    );
    void animation.finished.then(onClose).catch(() => {
      closing.current = false;
    });
  }
  useEffect(() => {
    const dialog = ref.current;
    dialog?.showModal();
    return () => {
      dialog?.close();
    };
  }, []);
  return (
    <dialog
      ref={ref}
      className="sheet"
      aria-labelledby={headingId}
      onCancel={(event) => {
        event.preventDefault();
        dismiss();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) dismiss();
      }}
    >
      <div className="sheet-inner">
        <div className="sheet-header">
          <div>
            {eyebrow && <p className="eyebrow">{eyebrow}</p>}
            <h2 id={headingId}>{title}</h2>
          </div>
          <button
            className="icon-button"
            aria-label="Close dialog"
            disabled={busy}
            onClick={dismiss}
          >
            <X size={22} />
          </button>
        </div>
        <div className="sheet-body">
          {error && (
            <p className="sheet-error" role="alert">
              {error}
            </p>
          )}
          {children}
        </div>
      </div>
    </dialog>
  );
}

export function Busy({
  children,
  busy,
}: {
  children: ReactNode;
  busy: boolean;
}) {
  return (
    <>
      {busy ? <CircleNotch className="spin" size={19} aria-hidden /> : null}
      {children}
    </>
  );
}

export const kes = (value: number) =>
  `KES ${new Intl.NumberFormat("en-KE", { maximumFractionDigits: 2 }).format(value)}`;
// Explicit fixed demo valuation: 1,000 sats = KES25; not a market quote.
export const demoKes = (sats: number) => sats / 40;
export const satsLabel = (sats: number) =>
  `${new Intl.NumberFormat("en-KE").format(sats)} sats`;
export function toSats(input: string) {
  const sats = Number(input) * 40;
  if (
    !input.trim() ||
    !Number.isSafeInteger(sats) ||
    sats <= 0 ||
    sats > 2_100_000_000_000_000
  )
    throw new Error(
      "Enter a positive amount that converts to whole sats at the demo rate.",
    );
  return sats;
}
