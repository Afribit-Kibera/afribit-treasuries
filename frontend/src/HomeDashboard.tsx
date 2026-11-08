import {
  ArrowRight,
  ArrowCounterClockwise,
  ChartLine,
  HandCoins,
  UsersThree,
  Checks,
} from "@phosphor-icons/react";
import type { ClanDetail } from "./live-api";
import { useRegion } from "./Region";
import { localMoney, useRate } from "./LocalMoney";

export function HomeDashboard({
  clan,
  request,
  repay,
  vote,
  activity,
  members,
  paymentReady = clan.treasury_ready,
  attentionCount,
}: {
  clan: ClanDetail;
  request: () => void;
  repay: () => void;
  vote: () => void;
  activity: () => void;
  members: () => void;
  paymentReady?: boolean;
  attentionCount?: number;
}) {
  const { currency, locale } = useRegion();
  const { rate, unavailable } = useRate(currency);
  const money = (msat: string) =>
    rate
      ? localMoney(msat, rate, true, locale)
      : `${new Intl.NumberFormat(locale).format(Number(msat) / 1000)} sats`;
  const attention =
    attentionCount ??
    clan.grants.filter((grant) => grant.can_vote || grant.payment?.can_approve)
      .length;
  return (
    <section className="clan-home" aria-label="Clan home">
      <button className="home-clan-name" onClick={members}>
        <UsersThree size={25} />
        <h1>{clan.name}</h1>
      </button>
      {!clan.governance_ready && (
        <button className="home-setup-link text-button" onClick={members}>
          Finish clan setup <ArrowRight size={16} />
        </button>
      )}
      {!paymentReady && (
        <p className="home-payment-status" role="status">
          Payments are paused. Please try again later.
        </p>
      )}
      <div className="home-balance">
        <span className="eyebrow">Available money</span>
        <h2 className="home-balance-number">{money(clan.available_msat)}</h2>
        <span className="balance-rule" />
        <div className="home-totals">
          <span>
            Grants given <strong>{money(clan.grants_given_msat)}</strong>
          </span>
          <span>
            Repaid <strong>{money(clan.grants_repaid_msat)}</strong>
          </span>
        </div>
        <details className="home-rate">
          <summary>
            {rate
              ? "About this amount"
              : unavailable
                ? `${currency} rate unavailable`
                : `Getting ${currency} rate…`}
          </summary>
          <p>
            {rate
              ? `Shown at the CoinGecko Bitcoin rate, updated ${new Date(rate.published_at * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}. The value can change. Grants asked for in KES are repaid in KES; others are kept in Bitcoin.`
              : "Showing Bitcoin sats until a fresh rate is available. You can change currency in Profile."}
          </p>
        </details>
      </div>
      {!!clan.access_recoveries?.length && (
        <button className="home-alert text-button" onClick={members}>
          A member needs help getting back in <ArrowRight size={17} />
        </button>
      )}
      <div className="paw-actions" aria-label="What would you like to do?">
        <button className="paw-action paw-receive" onClick={request}>
          <span className="paw-content">
            <HandCoins />
            <span>
              Receive
              <br />
              grant
            </span>
          </span>
        </button>
        <button className="paw-action paw-repay" onClick={repay}>
          <span className="paw-content">
            <ArrowCounterClockwise />
            <span>Repay</span>
          </span>
        </button>
        <button className="paw-action paw-vote" onClick={vote}>
          <span className="paw-content">
            <Checks />
            <span>Vote</span>
            {attention > 0 && (
              <small className="paw-count">{attention} to review</small>
            )}
          </span>
        </button>
      </div>
      <button className="home-activity" onClick={activity}>
        <ChartLine size={24} />
        <span>Activity</span>
        <ArrowRight size={19} />
      </button>
    </section>
  );
}
