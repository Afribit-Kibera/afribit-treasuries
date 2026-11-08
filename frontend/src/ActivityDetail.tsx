import { Fragment, useEffect, useState } from "react";
import {
  ArrowSquareOut,
  Coins,
  FileText,
  ShieldWarning,
  UserCircle,
  UserPlus,
  UsersThree,
  Wallet,
  type Icon,
} from "@phosphor-icons/react";
import {
  ApiError,
  getActivityDetail,
  type ActivityCategory,
  type ActivityDetail,
  type ActivityItem,
} from "./live-api";
import { Avatar, Busy, Sheet } from "./ui";
import { WalletPayout } from "./WalletPayout";
import { getPayout, type WalletView } from "./wallet-api";
import { walletMessage } from "./wallet-trust";
import type { ClanNetwork } from "./vault/policy";

/** One icon per kind of activity, not per event. */
const categories: Record<ActivityCategory, { icon: Icon; label: string }> = {
  clan: { icon: UsersThree, label: "Clan" },
  members: { icon: UserPlus, label: "Members" },
  grants: { icon: FileText, label: "Grants" },
  money: { icon: Coins, label: "Money" },
  wallet: { icon: Wallet, label: "Clan wallet" },
  security: { icon: ShieldWarning, label: "Security" },
  account: { icon: UserCircle, label: "Account" },
};
export function activityCategory(category: string | undefined) {
  return (
    categories[(category || "clan") as ActivityCategory] || categories.clan
  );
}
/** A title for a row, from the server, or from the app's own words for an older server. */
export function activityTitle(
  item: Pick<ActivityItem, "title" | "event">,
  labels: Record<string, string>,
) {
  return item.title || labels[item.event] || "Clan activity";
}
const explorers: Record<ClanNetwork, string> = {
  bitcoin: "https://mempool.space/tx/",
  signet: "https://mempool.space/signet/tx/",
  testnet4: "https://mempool.space/testnet4/tx/",
};
export function explorerLink(network: ClanNetwork | undefined, txid: string) {
  if (!network || !explorers[network] || !/^[0-9a-f]{64}$/i.test(txid))
    return null;
  return explorers[network] + txid.toLowerCase();
}
function when(at: string) {
  const date = new Date(at);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString(navigator.language || "en", {
    day: "numeric",
    month: "long",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

/** The page for one activity item: what happened, a few safe facts, and what it relates to. */
export function ActivityDetailSheet({
  clanId,
  item,
  labels,
  network,
  canOpenGrant,
  canOpenPayment,
  onOpenGrant,
  onOpenPayment,
  onClose,
}: {
  clanId: string;
  item: ActivityItem;
  labels: Record<string, string>;
  network?: ClanNetwork;
  canOpenGrant: (grantId: string) => boolean;
  canOpenPayment: boolean;
  onOpenGrant: (grantId: string) => void;
  onOpenPayment: (payoutId: string, grantId?: string) => void;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<ActivityDetail | null>(null);
  const [error, setError] = useState("");
  const [missing, setMissing] = useState(false);
  const [busy, setBusy] = useState(true);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let active = true;
    setBusy(true);
    setError("");
    setMissing(false);
    getActivityDetail(clanId, item.id)
      .then((value) => {
        if (active) setDetail(value);
      })
      .catch((e) => {
        if (!active) return;
        if (e instanceof ApiError && e.status === 404) setMissing(true);
        else setError((e as Error).message);
      })
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, [clanId, item.id, reload]);
  const shown = detail || item;
  const category = activityCategory(shown.category);
  const CategoryIcon = category.icon;
  const security = shown.category === "security";
  const links = detail?.links || {};
  const explorer = links.txid ? explorerLink(network, links.txid) : null;
  const grantLink =
    links.grant_id && canOpenGrant(links.grant_id) ? links.grant_id : null;
  const paymentLink = links.payout_id && canOpenPayment ? links.payout_id : null;
  return (
    <Sheet
      title={activityTitle(shown, labels)}
      eyebrow={category.label}
      onClose={onClose}
    >
      {missing ? (
        <div className="wallet-flow">
          <p role="alert">This activity isn't in your clan.</p>
        </div>
      ) : (
        <div className="wallet-flow activity-detail">
          <div className="requester-line activity-detail-who">
            <Avatar name={shown.actor} />
            <span>
              {shown.actor}
              {when(shown.at) && (
                <>
                  {" · "}
                  <time dateTime={shown.at}>{when(shown.at)}</time>
                </>
              )}
            </span>
          </div>
          {shown.summary && (
            <p
              className={
                security ? "activity-summary activity-security" : "activity-summary"
              }
            >
              <CategoryIcon size={22} aria-hidden="true" />
              <span>{shown.summary}</span>
            </p>
          )}
          {error && (
            <p role="alert" className="field-help">
              {error}{" "}
              <button
                className="text-button"
                disabled={busy}
                onClick={() => setReload((n) => n + 1)}
              >
                Try again
              </button>
            </p>
          )}
          {busy && !detail && (
            <div className="activity-skeleton" role="status">
              <Busy busy>Loading the details</Busy>
              <i />
            </div>
          )}
          {!!detail?.details.length && (
            <dl className="wallet-amounts">
              {detail.details.map((fact, i) => (
                <Fragment key={i}>
                  <dt>{fact.label}</dt>
                  <dd>{fact.value}</dd>
                </Fragment>
              ))}
            </dl>
          )}
          {(grantLink || paymentLink || explorer) && (
            <div className="activity-links">
              {grantLink && (
                <button
                  className="secondary-button"
                  onClick={() => onOpenGrant(grantLink)}
                >
                  <FileText size={20} aria-hidden="true" />
                  Open the grant
                </button>
              )}
              {paymentLink && (
                <button
                  className="secondary-button"
                  onClick={() =>
                    onOpenPayment(paymentLink, links.grant_id || undefined)
                  }
                >
                  <Coins size={20} aria-hidden="true" />
                  Open the payment
                </button>
              )}
              {explorer && (
                <a
                  className="secondary-button"
                  href={explorer}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <ArrowSquareOut size={20} aria-hidden="true" />
                  View on a block explorer
                </a>
              )}
            </div>
          )}
        </div>
      )}
    </Sheet>
  );
}

/**
 * Opens a clan wallet payment from its activity, in the same view the grant and wallet screens
 * use. A grant payment is checked against its grant, so find which grant it pays first.
 */
export function ActivityPaymentSheet({
  clanId,
  payoutId,
  grantId,
  view,
  userId,
  beneficiaryOf,
  onCheckWallet,
  onRefresh,
  onClose,
}: {
  clanId: string;
  payoutId: string;
  grantId?: string;
  view: WalletView;
  userId?: string;
  beneficiaryOf: (grantId: string) => string | undefined;
  onCheckWallet: () => void;
  onRefresh: () => Promise<unknown>;
  onClose: () => void;
}) {
  const [target, setTarget] = useState<{ grantId?: string } | null>(null);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let active = true;
    setTarget(null);
    setError("");
    getPayout(clanId, payoutId)
      .then((payout) => {
        if (!active) return;
        if (payout.clan_id !== clanId)
          throw Error("This payment does not match your clan.");
        if (payout.kind !== "grant") return setTarget({});
        const grants = payout.recipients.map((r) => r.grant_id);
        const paid =
          grantId && grants.includes(grantId) ? grantId : grants[0];
        if (!paid) throw Error("This payment does not match your clan.");
        setTarget({ grantId: paid });
      })
      .catch((e) => {
        if (active) setError(walletMessage(e));
      });
    return () => {
      active = false;
    };
  }, [clanId, payoutId, grantId, reload]);
  return (
    <Sheet title="Clan wallet payment" onClose={onClose}>
      {error ? (
        <div className="wallet-flow">
          <p role="alert">{error}</p>
          <button
            className="secondary-button"
            onClick={() => setReload((n) => n + 1)}
          >
            Try again
          </button>
        </div>
      ) : !target ? (
        <div className="activity-skeleton" role="status">
          <Busy busy>Loading the payment</Busy>
          <i />
        </div>
      ) : (
        <WalletPayout
          key={payoutId}
          clanId={clanId}
          payoutId={payoutId}
          grantId={target.grantId}
          view={view}
          isBeneficiary={
            !!target.grantId &&
            !!userId &&
            beneficiaryOf(target.grantId) === userId
          }
          onCheckWallet={onCheckWallet}
          onRefresh={onRefresh}
        />
      )}
    </Sheet>
  );
}
