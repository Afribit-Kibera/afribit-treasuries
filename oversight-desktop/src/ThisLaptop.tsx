import { useEffect, useState } from "react";
import { call } from "./core";
import type { Records } from "./types";
import { useApp } from "./state";
import {
  Busy,
  CopyButton,
  Notice,
  PageHeading,
  PassphraseField,
  Problem,
  kindLabel,
  sats,
  useFocusHeading,
  when,
} from "./ui";

function CheckPassphrase() {
  const [passphrase, setPassphrase] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<"right" | null>(null);
  const [error, setError] = useState<unknown>(null);

  async function check() {
    if (!passphrase || busy) return;
    const typed = passphrase;
    setPassphrase("");
    setBusy(true);
    setResult(null);
    setError(null);
    try {
      await call("check_passphrase", { passphrase: typed });
      setResult("right");
    } catch (reason) {
      setError(reason);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card" aria-labelledby="check-pass">
      <h2 id="check-pass" className="card-title">
        Check my passphrase
      </h2>
      <p className="muted">
        Proves your passphrase still opens this laptop's key. Nothing is signed or sent.
      </p>
      {result === "right" && <Notice tone="good" title="That's right. Your passphrase opens the key." />}
      {error !== null && <Problem error={error} />}
      <PassphraseField label="Passphrase" value={passphrase} onChange={setPassphrase} disabled={busy} />
      <div className="actions">
        <button className="secondary-button" disabled={busy || !passphrase} onClick={() => void check()}>
          <Busy busy={busy}>Check my passphrase</Busy>
        </button>
      </div>
    </section>
  );
}

export function ThisLaptop() {
  const app = useApp();
  const [records, setRecords] = useState<Records | null>(null);
  const [admin, setAdmin] = useState("");
  const [error, setError] = useState<unknown>(null);
  useFocusHeading("laptop");

  useEffect(() => {
    let active = true;
    Promise.all([call("records"), call("admin_lines")])
      .then(([found, lines]) => {
        if (!active) return;
        setRecords(found);
        setAdmin(lines.text);
      })
      .catch((reason) => active && setError(reason));
    return () => {
      active = false;
    };
  }, []);

  return (
    <div className="screen">
      <PageHeading eyebrow="This laptop" title="This laptop" />
      {error !== null && <Problem error={error} />}

      <section className="card" aria-labelledby="admin-lines">
        <h2 id="admin-lines" className="card-title">
          Administrator lines
        </h2>
        <p className="muted">
          Send these to the Clans administrator when they add this laptop. They hold no secret and
          can't approve anything.
        </p>
        {admin && (
          <>
            <pre className="admin-lines" tabIndex={0} aria-label="Lines for the administrator">
              {admin}
            </pre>
            <CopyButton value={admin} label="Copy the lines" />
          </>
        )}
      </section>

      <CheckPassphrase />

      {records && (
        <>
          <section className="card" aria-labelledby="approvals">
            <h2 id="approvals" className="card-title">
              Recent approvals
            </h2>
            {records.approvals.length ? (
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">When</th>
                    <th scope="col">Clan</th>
                    <th scope="col">Kind</th>
                    <th scope="col" className="num">
                      Total
                    </th>
                    <th scope="col" className="num">
                      Fee
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {records.approvals.map((item) => (
                    <tr key={item.txid + item.signed_at}>
                      <td>{when(item.signed_at)}</td>
                      <td>{item.clan_name || item.clan_id}</td>
                      <td>{kindLabel(item.kind)}</td>
                      <td className="num money">{sats(item.total_sats)}</td>
                      <td className="num money">{sats(item.fee_sats)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="muted">None yet.</p>
            )}
          </section>

          <section className="card" aria-labelledby="addresses">
            <h2 id="addresses" className="card-title">
              Addresses checked by phone
            </h2>
            {records.addresses.length ? (
              <ul className="address-records">
                {records.addresses.map((item) => (
                  <li key={item.address}>
                    <strong>{item.name || "Beneficiary"}</strong>
                    <code className="address">{item.address}</code>
                    <span className="muted">Checked {when(item.confirmed_at)}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">None yet.</p>
            )}
          </section>

          <section className="card" aria-labelledby="limits">
            <h2 id="limits" className="card-title">
              Limits
            </h2>
            <dl className="limits">
              <div>
                <dt>Highest network fee for a grant</dt>
                <dd className="money">{sats(records.settings.max_fee_sats)}</dd>
              </div>
              <div>
                <dt>Highest network fee for a refresh or move</dt>
                <dd className="money">{sats(records.settings.max_sweep_fee_sats)}</dd>
              </div>
              <div>
                <dt>A payout this size or more needs the total typed</dt>
                <dd className="money">{sats(records.settings.large_payout_sats)}</dd>
              </div>
            </dl>
          </section>

          <section className="card" aria-labelledby="records-file">
            <h2 id="records-file" className="card-title">
              This laptop's records
            </h2>
            <p>Copy this file to a USB stick now and then. It holds no secret.</p>
            <code className="file-path">{records.register_file}</code>
            <CopyButton value={records.register_file} label="Copy the file path" />
          </section>
        </>
      )}

      <section className="card" aria-labelledby="about">
        <h2 id="about" className="card-title">
          Connection
        </h2>
        <dl className="limits">
          <div>
            <dt>Clans address</dt>
            <dd>{app.status.server || "Not connected"}</dd>
          </div>
          <div>
            <dt>Data folder</dt>
            <dd>
              <code>{app.status.home}</code>
            </dd>
          </div>
        </dl>
      </section>
    </div>
  );
}
