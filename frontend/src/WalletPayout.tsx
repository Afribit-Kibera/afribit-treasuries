import { useEffect, useMemo, useRef, useState } from "react";
import { CheckCircle, Circle } from "@phosphor-icons/react";
import { Busy } from "./ui";
import { CopyButton } from "./CopyButton";
import { KeyUnlock } from "./WalletKeySetup";
import { WalletStop } from "./WalletCompare";
import { vaultStore, type Protection, type Unlock } from "./vault-access";
import { checkedWallet, publicSigningKey, walletMessage } from "./wallet-trust";
import { signPayout, signSweep } from "./vault/sign";
import {
  getPayout,
  getPayouts,
  getWallet,
  safeSats,
  submitPayoutSignature,
  toClanPolicy,
  type PayoutDraft,
  type PayoutStatus,
  type WalletView,
} from "./wallet-api";
import { keyExpression } from "./vault/policy";
import { reviewWalletPayment } from "./wallet-review";
import { useWalletMoney } from "./WalletMoney";
import { SpendAlarmWarning } from "./WalletAlarms";
import { communityName } from "./community";
const statuses: PayoutStatus[] = [
  "awaiting_signatures",
  "awaiting_oversight",
  "broadcasting",
  "broadcast",
  "confirmed",
  "replaced",
  "expired",
];
export function WalletPayout({
  clanId,
  grantId,
  payoutId,
  view,
  onCheckWallet,
  signingEnabled = true,
  onRefresh,
  isBeneficiary = false,
}: {
  clanId: string;
  grantId?: string;
  payoutId?: string;
  view: WalletView;
  onCheckWallet?: () => void;
  signingEnabled?: boolean;
  onRefresh?: () => Promise<unknown>;
  isBeneficiary?: boolean;
}) {
  const [draft, setDraft] = useState<PayoutDraft | null>(null),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(true),
    [busy, setBusy] = useState(false),
    [reload, setReload] = useState(0),
    [protection, setProtection] = useState<Protection | null>(null),
    [target, setTarget] = useState<string | null>(payoutId || null),
    [needsReview, setNeedsReview] = useState(false),
    [higherFee, setHigherFee] = useState<PayoutDraft | null>(null),
    [versionError, setVersionError] = useState("");
  const alive = useRef(true);
  const money = useWalletMoney();
  const onRefreshRef = useRef(onRefresh);
  onRefreshRef.current = onRefresh;
  function belongs(item: PayoutDraft) {
    if (
      item.clan_id !== clanId ||
      (grantId
        ? item.kind !== "grant" ||
          !item.recipients.some((r) => r.grant_id === grantId)
        : !["move", "refresh"].includes(item.kind)) ||
      !statuses.includes(item.status)
    )
      throw Error(
        "This payment does not match your clan and grant. Do not sign it.",
      );
    return item;
  }
  // Without a grant, only this screen's kind of payment (moves and refreshes) is listed.
  const mine = (list: PayoutDraft[]) =>
    (grantId ? list : list.filter((item) => item.kind !== "grant")).map(
      belongs,
    );
  async function loadCurrent(id?: string | null) {
    let item = id
      ? belongs(await getPayout(clanId, id))
      : mine(await getPayouts(clanId, { grantId }))[0];
    const seen = new Set<string>();
    while (item?.replaced_by) {
      if (seen.has(item.id) || seen.size >= 20)
        throw Error(
          `The payment versions could not be checked. Contact ${communityName()}.`,
        );
      seen.add(item.id);
      item = belongs(await getPayout(clanId, item.replaced_by));
    }
    return item || null;
  }
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, [clanId, grantId]);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    setDraft(null);
    setNeedsReview(false);
    void loadCurrent(target)
      .then(async (current) => {
        if (!active) return;
        setDraft(current);
        if (current?.status === "confirmed" && draft?.status !== "confirmed")
          try {
            await onRefreshRef.current?.();
          } catch {
            if (active)
              setError(
                "Payment confirmed. The grant could not be refreshed yet. Please open it again.",
              );
          }
      })
      .catch((e) => {
        if (active) setError(walletMessage(e));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [clanId, grantId, reload, target]);
  useEffect(() => {
    setHigherFee(null);
    setVersionError("");
    if (draft?.status !== "broadcast") return;
    let active = true;
    let running = false;
    async function find() {
      if (running) return;
      running = true;
      try {
        const waiting = await getPayouts(clanId, {
          grantId,
          status: "awaiting_signatures",
        });
        const next = mine(waiting).find((item) => item.replaces === draft!.id);
        if (active) {
          setHigherFee(next || null);
          setVersionError("");
        }
      } catch {
        if (active)
          setVersionError(
            "A newer payment could not be checked. Try checking its status again.",
          );
      } finally {
        running = false;
      }
    }
    void find();
    const timer = setInterval(() => void find(), 30000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [clanId, grantId, draft?.id, draft?.status, reload]);
  useEffect(() => {
    if (
      busy ||
      needsReview ||
      (draft && ["confirmed", "expired", "replaced"].includes(draft.status))
    )
      return;
    let active = true;
    const timer = setInterval(() => {
      void (draft ? getPayout(clanId, draft.id).then(belongs) : loadCurrent())
        .then(async (next) => {
          if (active) {
            setDraft(next);
            setError("");
            if (next?.status === "confirmed" && draft?.status !== "confirmed")
              try {
                await onRefreshRef.current?.();
              } catch {
                if (active)
                  setError(
                    "Payment confirmed. The grant could not be refreshed yet. Please open it again.",
                  );
              }
          }
        })
        .catch((e) => {
          if (active) setError(walletMessage(e));
        });
    }, 30000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [clanId, grantId, draft?.id, draft?.status, busy, needsReview]);
  const checked = useMemo(() => {
    if (!draft) return null;
    try {
      belongs(draft);
      return reviewWalletPayment(clanId, view, draft);
    } catch (e) {
      return { error: walletMessage(e) };
    }
  }, [draft, view, clanId]);
  const canSign =
    !!draft &&
    !!checked &&
    !("error" in checked) &&
    !error &&
    view.enabled &&
    view.status === "active" &&
    view.me.is_signer &&
    draft.status === "awaiting_signatures" &&
    !draft.signatures.signed_by_me &&
    signingEnabled &&
    !isBeneficiary &&
    (!checked.sourceKey || checked.sourceKey === view.me.key);
  async function sign(unlock: Unlock) {
    if (!canSign || !draft || !checked || "error" in checked) return;
    setBusy(true);
    setError("");
    let words = "";
    try {
      const latest = await getPayout(clanId, draft.id);
      const current = await getWallet(clanId);
      if (!alive.current) return;
      if (JSON.stringify(latest) !== checked.snapshot)
        throw Error(
          "The payment changed. Refresh and check the new version before signing.",
        );
      if (
        !current.enabled ||
        current.status !== "active" ||
        !current.me.is_signer ||
        current.generation !== view.generation
      )
        throw Error("Your clan wallet changed. Compare its code again.");
      checkedWallet(clanId, current, draft.generation);
      const reviewed = reviewWalletPayment(clanId, current, latest);
      if (
        JSON.stringify(reviewed.policy) !== JSON.stringify(checked.policy) ||
        (reviewed.kind === "sweep" &&
          checked.kind === "sweep" &&
          JSON.stringify(reviewed.expected.destination) !==
            JSON.stringify(checked.expected.destination))
      )
        throw Error("The wallet changed. Compare its code again.");
      words = await (await vaultStore()).openVault(clanId, unlock);
      if (!alive.current) return;
      const own = publicSigningKey(words, checked.policy.network);
      if (
        own !== checked.sourceKey ||
        !checked.policy.signers.some((key) => keyExpression(key) === own)
      )
        throw Error(
          "Your key changed, so the other signatories sign this one.",
        );
      const signed =
        checked.kind === "grant"
          ? signPayout(draft.psbt, words, checked.policy, checked.expected)
          : signSweep(draft.psbt, words, checked.policy, checked.expected);
      words = "";
      const next = await submitPayoutSignature(clanId, draft.id, signed);
      if (alive.current) {
        setDraft(next);
        setProtection(null);
      }
    } catch (e) {
      if (alive.current) {
        setError(walletMessage(e));
        setNeedsReview(true);
        setProtection(null);
      }
    } finally {
      words = "";
      if (alive.current) setBusy(false);
    }
  }
  if (loading) return <Busy busy>Checking this payment</Busy>;
  return (
    <section className="wallet-flow" aria-label="Clan wallet payout">
      {error && <p role="alert">{error}</p>}
      {(!draft || error) && (
        <button
          className="secondary-button"
          disabled={busy}
          onClick={() => {
            setProtection(null);
            setReload((n) => n + 1);
          }}
        >
          Refresh payout
        </button>
      )}
      {!draft && !error && (
        <p>
          The payment is not ready yet. The member must accept the grant and add
          their Bitcoin address first.
        </p>
      )}
      {checked && "error" in checked ? (
        <>
          <WalletStop message={checked.error!} />
          {onCheckWallet && (
            <button className="secondary-button" onClick={onCheckWallet}>
              Open Clan and check wallet code
            </button>
          )}
        </>
      ) : (
        draft &&
        checked && (
          <>
            <p>
              <CheckCircle size={20} /> Checked on this phone
            </p>
            <p role="status">
              {
                {
                  awaiting_signatures: "Waiting for signatories",
                  awaiting_oversight: `Waiting for ${communityName()}`,
                  broadcasting: "Sending",
                  broadcast: "Sent",
                  confirmed: "Confirmed",
                  expired: "Address changed",
                  replaced: "Another version was sent",
                }[draft.status]
              }
            </p>
            {draft.replaces &&
              !["expired", "replaced"].includes(draft.status) && (
                <div className="wallet-flow">
                  <p>
                    This is a new version of an earlier payment. Check the
                    receiving address, amount and network fee again. It needs
                    fresh signatures.
                  </p>
                  <button
                    className="text-button"
                    disabled={busy}
                    onClick={() => {
                      setProtection(null);
                      setTarget(draft.replaces);
                      setReload((n) => n + 1);
                    }}
                  >
                    View earlier payment
                  </button>
                </div>
              )}
            {higherFee && draft.status === "broadcast" && (
              <div className="wallet-flow">
                <p>
                  Taking longer than usual. A version with a higher fee needs
                  your signature.
                </p>
                <button
                  className="secondary-button"
                  disabled={busy}
                  onClick={() => {
                    setProtection(null);
                    setTarget(higherFee.id);
                    setReload((n) => n + 1);
                  }}
                >
                  Review higher-fee payment
                </button>
              </div>
            )}
            {versionError && <p role="alert">{versionError}</p>}
            {checked.kind === "grant" &&
              draft.recipients.map((r, i) => (
                <div key={r.grant_id}>
                  <h3>Payment to {r.name}</h3>
                  <details>
                    <summary className="wallet-address">
                      {r.address.slice(0, 10)}…{r.address.slice(-8)}
                    </summary>
                    <p className="wallet-address">{r.address}</p>
                  </details>
                  <CopyButton value={r.address} label="Copy Bitcoin address" />
                  <dl className="wallet-amounts">
                    <dt>Approved amount</dt>
                    <dd>{money(safeSats(r.approved_sats))}</dd>
                    <dt>Member receives</dt>
                    <dd>{money(checked.received[i].amountSats)}</dd>
                  </dl>
                </div>
              ))}
            {checked.kind === "sweep" && (
              <>
                <h3>
                  {draft.kind === "move"
                    ? `Move to the clan's new wallet (generation ${draft.destination!.generation})`
                    : "Refresh the clan wallet"}
                </h3>
                <p>
                  {draft.kind === "move"
                    ? `The money stays with your clan. Signatories from the old wallet and ${communityName()} approve this move.`
                    : "The clan's coins go back to its own wallet, so the 6-month recovery wait starts again."}
                </p>
                <p>From wallet generation {draft.generation}</p>
                <details>
                  <summary>Clan receiving address</summary>
                  <p className="wallet-address">{checked.review.address}</p>
                </details>
                <CopyButton
                  value={checked.review.address}
                  label="Copy clan address"
                />
                <dl className="wallet-amounts">
                  <dt>Money moved after fee</dt>
                  <dd>{money(checked.review.amountSats)}</dd>
                </dl>
              </>
            )}
            <dl className="wallet-amounts">
              <dt>Network fee</dt>
              <dd>{money(checked.review.feeSats)}</dd>
              <dt>Highest network fee</dt>
              <dd>{money(checked.expected.maxFeeSats)}</dd>
              <dt>Who pays it</dt>
              <dd>
                {checked.kind === "grant"
                  ? "The members receiving money"
                  : "The clan"}
              </dd>
            </dl>
            <p>
              {draft.signatures.count} of {draft.signatures.required}{" "}
              signatories, then {communityName()}
              {draft.signatures.names.length
                ? `: ${draft.signatures.names.join(", ")}`
                : ""}
              .
            </p>
            <ol className="wallet-timeline">
              {[
                "Waiting for signatories",
                `Waiting for ${communityName()}`,
                "Sending",
                "Sent",
                "Confirmed",
              ].map((label, i) => (
                <li
                  key={label}
                  aria-current={
                    [
                      "awaiting_signatures",
                      "awaiting_oversight",
                      "broadcasting",
                      "broadcast",
                      "confirmed",
                    ].indexOf(draft.status) === i
                      ? "step"
                      : undefined
                  }
                >
                  {[
                    "awaiting_signatures",
                    "awaiting_oversight",
                    "broadcasting",
                    "broadcast",
                    "confirmed",
                  ].indexOf(draft.status) >= i ? (
                    <CheckCircle size={20} weight="fill" />
                  ) : (
                    <Circle size={20} />
                  )}
                  {label}
                  {i === 4 && draft.confirmations > 0
                    ? ` · ${draft.confirmations} confirmations`
                    : ""}
                </li>
              ))}
            </ol>
            <button
              className="secondary-button"
              disabled={busy}
              onClick={() => {
                setProtection(null);
                setReload((n) => n + 1);
              }}
            >
              Check payout status
            </button>
            {checked.sourceKey && checked.sourceKey !== view.me.key && (
              <p>Your key changed, so the other signatories sign this one.</p>
            )}
            {!signingEnabled && (
              <p>Payments are paused. You can still check this payment.</p>
            )}
            {isBeneficiary && draft.status === "awaiting_signatures" && (
              <p>
                The other signatories must sign this payment. You cannot sign a
                payment to yourself.
              </p>
            )}
            {draft.status === "replaced" && (
              <>
                <p>
                  Another version of this payment went out instead. Open that
                  version to check its progress.
                </p>
              </>
            )}
            {draft.status === "expired" && (
              <p>
                {draft.kind === "grant"
                  ? "The receiving address changed."
                  : "This wallet payment is no longer needed."}{" "}
                This version cannot be signed. Open the new payment and check it
                again.
              </p>
            )}
            {["expired", "replaced"].includes(draft.status) &&
              (draft.replaced_by ? (
                <button
                  className="secondary-button"
                  disabled={busy}
                  onClick={() => {
                    setProtection(null);
                    setTarget(draft.replaced_by);
                    setReload((n) => n + 1);
                  }}
                >
                  Open the latest payment
                </button>
              ) : (
                <button
                  className="secondary-button"
                  disabled={busy}
                  onClick={() => {
                    setTarget(null);
                    setReload((n) => n + 1);
                  }}
                >
                  Check for a newer payment
                </button>
              ))}
            {canSign && (
              <SpendAlarmWarning clanId={clanId} generation={view.generation} />
            )}
            {canSign && !protection && (
              <button
                className="primary-button"
                disabled={busy || !!error}
                onClick={async () => {
                  setBusy(true);
                  setError("");
                  try {
                    const kind = await (
                      await vaultStore()
                    ).vaultProtection(clanId);
                    if (!kind)
                      throw Error(
                        "Restore your signing key on this phone first.",
                      );
                    setProtection(kind);
                  } catch (e) {
                    setError(walletMessage(e));
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                <Busy busy={busy}>Sign payout</Busy>
              </button>
            )}
            {canSign && protection && (
              <KeyUnlock protection={protection} busy={busy} onUnlock={sign} />
            )}
          </>
        )
      )}
    </section>
  );
}
