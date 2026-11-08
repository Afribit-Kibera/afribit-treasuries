import { useEffect, useState } from "react";
import { CaretDown, CaretUp, Wallet } from "@phosphor-icons/react";
import { call } from "./core";
import type { Clan, FundingAddress } from "./types";
import { useApp } from "./state";
import { Address, Busy, CopyButton, PageHeading, Problem, networkLabel, useFocusHeading } from "./ui";

function Funding({ clan }: { clan: Clan }) {
  const [open, setOpen] = useState(false);
  const [found, setFound] = useState<FundingAddress | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function toggle() {
    if (open) return setOpen(false);
    setOpen(true);
    if (found) return;
    setBusy(true);
    setError(null);
    try {
      setFound(await call("funding_address", { clan_id: clan.clan_id }));
    } catch (reason) {
      setError(reason);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="funding">
      <button
        className="secondary-button"
        aria-expanded={open}
        aria-controls={`funding-${clan.clan_id}`}
        onClick={() => void toggle()}
      >
        <Busy busy={busy}>
          Address for funding {open ? <CaretUp size={16} aria-hidden /> : <CaretDown size={16} aria-hidden />}
        </Busy>
      </button>
      {open && (
        <div id={`funding-${clan.clan_id}`} className="funding-body">
          {error !== null && <Problem error={error} />}
          {found && (
            <>
              <p>
                Send funding for {clan.clan_name || "this clan"} only to this address. It's worked out
                on this laptop from the registered wallet, not taken from Clans.
              </p>
              <Address value={found} large />
              <p className="check-sentence">
                On the sending wallet, check that the 6 characters after{" "}
                <code className="inline-code">{found.fixed_start}</code> are{" "}
                <mark>{found.check_start}</mark>, and the last 6 are <mark>{found.check_end}</mark>.
              </p>
              <CopyButton value={found.address} label="Copy the address" />
            </>
          )}
        </div>
      )}
    </div>
  );
}

export function Clans() {
  const app = useApp();
  const [error, setError] = useState<unknown>(null);
  const [loaded, setLoaded] = useState(false);
  useFocusHeading("clans");

  useEffect(() => {
    let active = true;
    app
      .reloadClans()
      .catch((reason) => active && setError(reason))
      .finally(() => active && setLoaded(true));
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const toRegister = app.overview?.answered ? app.overview.wallets_to_register : [];

  return (
    <div className="screen">
      <PageHeading eyebrow="Clans" title="Clan wallets on this laptop" />
      {error !== null && <Problem error={error} />}

      {toRegister.length > 0 && (
        <section className="todo" aria-labelledby="clans-new">
          <h2 id="clans-new" className="section-title">
            Waiting to be registered
          </h2>
          <ul className="todo-list">
            {toRegister.map((wallet) => (
              <li key={`${wallet.clan_id}-${wallet.generation}`} className="todo-item">
                <Wallet size={26} aria-hidden />
                <div>
                  <strong>{wallet.clan_name || `Clan ${wallet.clan_id}`}</strong>
                  <p>
                    Wallet {wallet.generation}. Phone a signatory for the wallet code.
                  </p>
                </div>
                <button className="secondary-button" onClick={() => app.go({ name: "register", wallet })}>
                  Register
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {loaded && !app.clans.length && !error && (
        <p className="lead">
          No clan wallet is registered on this laptop yet. New wallets show on Home, with what to
          ask by phone.
        </p>
      )}

      {app.clans.length > 0 && (
        <ul className="clan-list">
          {app.clans.map((clan) => (
            <li key={clan.clan_id} className="card clan-card">
              <div className="clan-head">
                <div>
                  <h2>{clan.clan_name || `Clan ${clan.clan_id}`}</h2>
                  <p className="muted">
                    Wallet {clan.generation} · needs {clan.threshold} of {clan.signers} signatories ·{" "}
                    {networkLabel(clan.network)}
                  </p>
                </div>
                <div className="wallet-code-box">
                  <span className="eyebrow">Wallet code</span>
                  <span className="wallet-code">{clan.wallet_code}</span>
                </div>
              </div>
              <Funding clan={clan} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
