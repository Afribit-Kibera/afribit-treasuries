import { ArrowClockwise, ArrowRight, Bell, CheckCircle, Phone, Wallet } from "@phosphor-icons/react";
import { useApp } from "./state";
import { sentence } from "./core";
import type { PayoutSummary } from "./types";
import {
  Busy,
  Notice,
  PageHeading,
  Problem,
  clock,
  kindLabel,
  plural,
  sats,
  useFocusHeading,
  when,
} from "./ui";

function payoutTitle(payout: PayoutSummary) {
  if (payout.kind === "grant") {
    const names = payout.beneficiaries.filter(Boolean);
    return names.length ? `Grant to ${names.join(", ")}` : "Grant";
  }
  return kindLabel(payout.kind);
}

export function Home() {
  const app = useApp();
  const { overview, overviewError, checking, checkedAt } = app;
  useFocusHeading("home");

  const checkButton = (
    <button className="secondary-button" onClick={() => void app.refresh()} disabled={checking}>
      <Busy busy={checking}>
        {!checking && <ArrowClockwise size={18} aria-hidden />}
        Check again
      </Busy>
    </button>
  );
  const community = overview?.answered ? overview.community : null;

  return (
    <div className="screen">
      <PageHeading eyebrow="Home" title={community ? `Oversight for ${community}` : "Oversight"}>
        <p className="checked-at" role="status">
          {checking ? "Checking Clans…" : checkedAt ? `Last checked ${clock(checkedAt)}` : ""}
        </p>
        {checkButton}
      </PageHeading>

      {app.flash && (
        <Notice tone="info">
          <p>{app.flash}</p>
          <button className="text-button" onClick={() => app.setFlash("")}>
            OK
          </button>
        </Notice>
      )}

      {overviewError !== null && <Problem error={overviewError} />}

      {!overview && !overviewError && <p className="quiet-line">Checking what's waiting for you…</p>}

      {overview && !overview.answered && overview.reason === "not_added" && (
        <section className="card state-card">
          <h2>Clans isn't ready for this laptop yet</h2>
          <p>
            Send the administrator the lines from <strong>This laptop → Administrator lines</strong>,
            then check again.
          </p>
          <div className="actions">
            <button className="primary-button" onClick={() => app.go({ name: "laptop" })}>
              Show the administrator lines
            </button>
            {checkButton}
          </div>
        </section>
      )}

      {overview && !overview.answered && overview.reason === "unreachable" && (
        <section className="card state-card">
          <h2>Can't reach Clans</h2>
          <p>{sentence(overview.message)}</p>
          <p className="muted">Check the internet connection, then check again.</p>
          <div className="actions">{checkButton}</div>
        </section>
      )}

      {overview?.answered && (
        <>
          {overview.alarms.length > 0 && (
            <section className="alarm-banner" aria-labelledby="home-alarms">
              <Bell size={26} weight="fill" aria-hidden />
              <div>
                <h2 id="home-alarms">
                  {plural(overview.alarms.length, "new alarm")}. Read{" "}
                  {overview.alarms.length === 1 ? "it" : "them"} first.
                </h2>
                <p>You can't approve payouts until you've read the new alarms.</p>
              </div>
              <button className="primary-button" onClick={() => app.go({ name: "alarms" })}>
                Read the alarms <ArrowRight size={18} aria-hidden />
              </button>
            </section>
          )}

          {overview.wallets_to_register.length > 0 && (
            <section className="todo" aria-labelledby="home-wallets">
              <h2 id="home-wallets" className="section-title">
                Clan wallets to register
              </h2>
              <ul className="todo-list">
                {overview.wallets_to_register.map((wallet) => (
                  <li key={`${wallet.clan_id}-${wallet.generation}`} className="todo-item">
                    <Wallet size={26} aria-hidden />
                    <div>
                      <strong>{wallet.clan_name || `Clan ${wallet.clan_id}`}</strong>
                      <p>
                        {wallet.generation > 1
                          ? `Moved to a new wallet (wallet ${wallet.generation}).`
                          : "New clan wallet."}{" "}
                        <Phone size={16} aria-hidden /> Phone a signatory for the wallet code.
                      </p>
                    </div>
                    <button
                      className="secondary-button"
                      onClick={() => app.go({ name: "register", wallet })}
                    >
                      Register
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {overview.payouts.length > 0 && (
            <section className="todo" aria-labelledby="home-payouts">
              <h2 id="home-payouts" className="section-title">
                Payouts to approve
              </h2>
              <ul className="todo-list">
                {overview.payouts.map((payout) => (
                  <li key={payout.id} className="todo-item">
                    <span className="kind-dot" aria-hidden />
                    <div>
                      <strong>
                        {payout.clan_name || `Clan ${payout.clan_id}`} · {payoutTitle(payout)}
                      </strong>
                      <p>
                        {payout.kind === "grant" && <span className="money">{sats(payout.approved_sats)}</span>}
                        {payout.kind === "grant" && " approved · "}
                        {payout.created_at ? `asked ${when(payout.created_at)}` : ""}
                      </p>
                    </div>
                    <button
                      className="primary-button"
                      onClick={() => app.go({ name: "payout", id: payout.id })}
                    >
                      Open
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {!overview.alarms.length &&
            !overview.wallets_to_register.length &&
            !overview.payouts.length && (
              <section className="all-clear">
                <CheckCircle size={44} aria-hidden />
                <h2>Nothing is waiting for you.</h2>
                <p>Clans is checked again every few minutes while this window is open.</p>
              </section>
            )}
        </>
      )}
    </div>
  );
}
