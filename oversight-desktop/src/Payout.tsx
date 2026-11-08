import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  ArrowLeft,
  CheckCircle,
  CircleNotch,
  HandPalm,
  Phone,
  SealCheck,
} from "@phosphor-icons/react";
import { call, isReason, sentence } from "./core";
import type { Approved, PayoutStep, PayoutSummary, Review } from "./types";
import { useApp } from "./state";
import {
  Address,
  Busy,
  CopyButton,
  Notice,
  PageHeading,
  PassphraseField,
  Problem,
  kindLabel,
  networkLabel,
  sats,
  useFocusHeading,
} from "./ui";
import { RegisterWallet } from "./RegisterWallet";

const PASSPHRASE_TRIES = 3;

function title(payout: PayoutSummary) {
  const clan = payout.clan_name || `Clan ${payout.clan_id}`;
  if (payout.kind !== "grant") return `${clan} · ${kindLabel(payout.kind)}`;
  const names = payout.beneficiaries.filter(Boolean);
  return `${clan} · Grant${names.length ? ` to ${names.join(", ")}` : ""}`;
}

function DontApprove({ onHome }: { onHome: () => void }) {
  return (
    <div className="stop-box" role="alert">
      <HandPalm size={30} weight="fill" aria-hidden />
      <div>
        <h2>Don't approve this payout.</h2>
        <p>Tell the clan and the team. Nothing was signed, and the payout stays waiting.</p>
        <div className="actions">
          <button className="secondary-button" onClick={onHome}>
            <ArrowLeft size={18} aria-hidden /> Back to Home
          </button>
        </div>
      </div>
    </div>
  );
}

function AddressCheck({
  step,
  onConfirmed,
  onHome,
}: {
  step: Extract<PayoutStep, { step: "address" }>;
  onConfirmed: () => void;
  onHome: () => void;
}) {
  const half = step.characters / 2;
  const who = step.name || "the beneficiary";
  // Bech32 addresses are all lower case, so case doesn't matter there. Older ones keep it.
  const lower = /^(tb1|bc1|bcrt1)/i.test(step.fixed_start);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [tries, setTries] = useState(0);
  const [error, setError] = useState<unknown>(null);
  const [mismatch, setMismatch] = useState(false);
  const [stopped, setStopped] = useState(false);
  const [busy, setBusy] = useState(false);
  useFocusHeading(`address-${step.line}`);

  const clean = (value: string) => {
    const bare = value.replace(/\s/g, "").slice(0, half);
    return lower ? bare.toLowerCase() : bare;
  };

  async function check(event: FormEvent) {
    event.preventDefault();
    if (busy || start.length !== half || end.length !== half) return;
    setBusy(true);
    setError(null);
    try {
      await call("confirm_address", {
        payout_id: step.payout.id,
        line: step.line,
        characters: start + end,
      });
      onConfirmed();
    } catch (reason) {
      setError(reason);
      setMismatch(isReason(reason, "address_mismatch"));
      setTries(tries + 1);
    } finally {
      setBusy(false);
    }
  }

  if (stopped) return <DontApprove onHome={onHome} />;

  const canRetry = mismatch && tries < 2;
  return (
    <>
      <PageHeading eyebrow={title(step.payout)} title={`New address for ${who}`} />
      <p className="lead">This is the first payment to this address, so check it by phone.</p>
      <ol className="phone-steps">
        <li>
          <Phone size={20} aria-hidden /> Phone {who}.
        </li>
        <li>Ask them to open their own wallet app and find the address they gave for this payment.</li>
        <li>
          Ask them to read you the {half} characters right after the start (
          <code className="inline-code">{step.fixed_start}</code>), then the last {half}.
        </li>
      </ol>
      <p className="muted spaced-hint">The screen never shows the expected characters. Type what you hear.</p>

      {error !== null && (
        <Problem error={error}>
          {mismatch && (
            <p className="problem-strong">Don't approve this payout. Tell the clan and the team.</p>
          )}
        </Problem>
      )}

      {(!mismatch || canRetry) && (
        <form className="card" onSubmit={(event) => void check(event)}>
          {mismatch && <p className="muted">If you think you typed it wrong, ask them to read it again, slowly.</p>}
          <div className="char-boxes">
            <div className="field">
              <label htmlFor="check-start">
                {half} characters after <code className="inline-code">{step.fixed_start}</code>
              </label>
              <input
                id="check-start"
                className="code-input"
                value={start}
                autoComplete="off"
                autoCapitalize="off"
                autoCorrect="off"
                spellCheck={false}
                autoFocus
                disabled={busy}
                onChange={(event) => {
                  const value = clean(event.target.value);
                  setStart(value);
                  if (value.length === half) document.getElementById("check-end")?.focus();
                }}
              />
              <p className="field-hint">{start.length} of {half}</p>
            </div>
            <div className="field">
              <label htmlFor="check-end">Last {half} characters</label>
              <input
                id="check-end"
                className="code-input"
                value={end}
                autoComplete="off"
                autoCapitalize="off"
                autoCorrect="off"
                spellCheck={false}
                disabled={busy}
                onChange={(event) => setEnd(clean(event.target.value))}
              />
              <p className="field-hint">{end.length} of {half}</p>
            </div>
          </div>
          <div className="actions">
            <button type="button" className="secondary-button" onClick={() => setStopped(true)}>
              They read something different: stop
            </button>
            <button
              className="primary-button"
              disabled={busy || start.length !== half || end.length !== half}
            >
              <Busy busy={busy}>Check</Busy>
            </button>
          </div>
        </form>
      )}
      {mismatch && !canRetry && <DontApprove onHome={onHome} />}
    </>
  );
}

function ReviewApprove({
  step,
  onApproved,
  onReopen,
}: {
  step: Extract<PayoutStep, { step: "review" }>;
  onApproved: (result: Approved) => void;
  onReopen: () => void;
}) {
  const app = useApp();
  const review: Review = step.review;
  const [passphrase, setPassphrase] = useState("");
  const [typedTotal, setTypedTotal] = useState("");
  const [wrong, setWrong] = useState(0);
  const [error, setError] = useState<unknown>(null);
  const [changed, setChanged] = useState(false);
  const [busy, setBusy] = useState(false);
  const [reporting, setReporting] = useState(false);
  useFocusHeading(`review-${review.txid}`);

  const clan = app.clans.find((item) => item.clan_id === review.clan_id);
  const grant = review.kind === "grant";
  const payer = review.fee_paid_by === "recipients" ? "the beneficiaries" : "the clan";
  const blocked = app.unread > 0;
  // The core counts alarms when the payout opens; don't let an older count on Home hide new ones.
  const { setUnread } = app;
  useEffect(() => {
    if (step.unread_alarms > 0) setUnread((count) => Math.max(count, step.unread_alarms));
  }, [step.unread_alarms, setUnread]);
  const totalReady = !review.large || typedTotal.replace(/[,\s]/g, "").length > 0;

  async function approve() {
    if (busy || blocked || !passphrase || !totalReady) return;
    const typed = passphrase;
    // Gone from state before the call starts, whatever happens next.
    setPassphrase("");
    setBusy(true);
    setError(null);
    setChanged(false);
    try {
      const result = await call("approve", {
        payout_id: step.payout.id,
        passphrase: typed,
        shown: { txid: review.txid, total_sats: review.total_sats },
        ...(review.large ? { typed_total: typedTotal } : {}),
      });
      app.changed();
      onApproved(result);
    } catch (reason) {
      if (isReason(reason, "wrong_passphrase")) {
        const count = wrong + 1;
        setWrong(count);
        if (count >= PASSPHRASE_TRIES) {
          app.setFlash("The passphrase was wrong three times. Nothing was signed.");
          app.go({ name: "home" });
          return;
        }
        setError(null);
      } else {
        setError(reason);
        setChanged(isReason(reason, "payout_changed"));
        if (isReason(reason, "alarms_unread")) {
          app.setUnread(Math.max(app.unread, 1));
          app.changed();
        }
      }
    } finally {
      setBusy(false);
    }
  }

  const reference = `Clan: ${review.clan_name || review.clan_id} (${review.clan_id})\nPayout: ${step.payout.id}\nPayment: ${review.txid}`;

  return (
    <>
      <PageHeading eyebrow="Review and approve" title={title(step.payout)}>
        {clan && (
          <span className={`network-pill ${clan.network === "bitcoin" ? "pill-mainnet" : "pill-test"}`}>
            {networkLabel(clan.network)}
            {clan.network === "bitcoin" ? ": real money" : ": not real money"}
          </span>
        )}
      </PageHeading>

      {review.already_signed && (
        <Notice tone="info" title="This laptop already signed this exact payment.">
          <p>Approving again sends the same signature. It can't pay twice.</p>
        </Notice>
      )}
      {review.replaces.length > 0 && (
        <Notice tone="info" title="A higher-fee version of a payment this laptop approved.">
          <p>
            It replaces {review.replaces.map((txid) => `${txid.slice(0, 8)}…${txid.slice(-8)}`).join(", ")}.
            Only one of them can ever go through.
          </p>
        </Notice>
      )}

      <section className="card review-card" aria-label="What's being paid">
        <p className="review-kind">
          <SealCheck size={20} weight="fill" aria-hidden /> Checked by this laptop against its own
          copy of the clan wallet
        </p>
        {!grant && (
          <p className="lead">No beneficiary: the clan's money stays in the clan's own wallets.</p>
        )}
        <ul className="review-lines">
          {review.lines.map((line, index) => (
            <li key={index} className="review-line">
              <div className="review-line-head">
                <strong>{line.name || (grant ? "Beneficiary" : kindLabel(review.kind))}</strong>
                <span className="money big-money">
                  {grant ? `receives ${sats(line.received_sats)}` : sats(line.received_sats)}
                </span>
              </div>
              {grant && (
                <p className="muted">
                  Approved <span className="money">{sats(line.approved_sats)}</span>
                </p>
              )}
              <p className="address-label">{grant ? "To this address" : "To the clan's own address"}</p>
              <Address value={line} />
              <p className="field-hint">
                Highlighted: the {line.check_start.length} characters after {line.fixed_start}, and the
                last {line.check_end.length}.
              </p>
            </li>
          ))}
        </ul>
        <dl className="review-sums">
          <div>
            <dt>Network fee</dt>
            <dd>
              <span className="money">{sats(review.fee_sats)}</span>, paid by {payer}
            </dd>
          </div>
          <div className="review-total">
            <dt>Total approved</dt>
            <dd className="money">{sats(review.total_sats)}</dd>
          </div>
        </dl>
        <details className="details">
          <summary>Technical details</summary>
          <dl className="detail-list">
            <div className="detail-row">
              <dt>Payment (txid)</dt>
              <dd>
                <code>{review.txid}</code>
              </dd>
            </div>
            <div className="detail-row">
              <dt>Wallet</dt>
              <dd>Wallet {review.generation}</dd>
            </div>
            <div className="detail-row">
              <dt>Payout id</dt>
              <dd>{step.payout.id}</dd>
            </div>
          </dl>
        </details>
      </section>

      {grant && (
        <p className="question">Check these details match what you know about this grant.</p>
      )}

      <section className="card approve-card" aria-labelledby="approve-title">
        <h2 id="approve-title">Approve</h2>
        {blocked && (
          <Notice tone="warning" title="Read the new alarms first">
            <p>There are new alarms. Approving stays off until you've read them.</p>
            <button className="text-button" onClick={() => app.go({ name: "alarms" })}>
              Go to Alarms
            </button>
          </Notice>
        )}
        {wrong > 0 && (
          <Notice tone="warning" title="That passphrase is wrong.">
            <p>
              Try again. {PASSPHRASE_TRIES - wrong} {PASSPHRASE_TRIES - wrong === 1 ? "try" : "tries"} left.
              Nothing was signed.
            </p>
          </Notice>
        )}
        {error !== null && (
          <Problem error={error}>
            {changed && (
              <button className="text-button" onClick={onReopen}>
                Open it again
              </button>
            )}
          </Problem>
        )}
        {review.large && (
          <div className="field">
            <label htmlFor="typed-total">Type the total approved sats</label>
            <input
              id="typed-total"
              className="code-input"
              inputMode="numeric"
              value={typedTotal}
              autoComplete="off"
              disabled={busy || blocked}
              onChange={(event) => setTypedTotal(event.target.value)}
            />
            <p className="field-hint">This is a large payout. Commas and spaces are fine.</p>
          </div>
        )}
        <PassphraseField
          label="Your passphrase"
          value={passphrase}
          onChange={setPassphrase}
          disabled={busy || blocked}
          hint="Typing it is your approval. Enter doesn't approve: use the button."
        />
        {busy && (
          <p className="working" role="status">
            <CircleNotch className="spin" size={18} aria-hidden /> Checking the payout again and
            signing…
          </p>
        )}
        <div className="actions approve-actions">
          <button className="secondary-button" disabled={busy} onClick={() => app.go({ name: "home" })}>
            Skip for now
          </button>
          <button className="secondary-button" disabled={busy} onClick={() => setReporting(true)}>
            Stop and report
          </button>
          <button
            className="primary-button"
            disabled={busy || blocked || !passphrase || !totalReady}
            onClick={() => void approve()}
          >
            <Busy busy={busy}>Approve with passphrase</Busy>
          </button>
        </div>
        {reporting && (
          <div className="report-box" role="status">
            <p>
              <strong>Nothing was signed.</strong> Tell the clan and the team why you stopped, and send
              them this reference:
            </p>
            <pre className="admin-lines">{reference}</pre>
            <CopyButton value={reference} label="Copy the reference" />
          </div>
        )}
      </section>
    </>
  );
}

export function PayoutFlow({ payoutId }: { payoutId: string }) {
  const app = useApp();
  const [step, setStep] = useState<PayoutStep | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [approved, setApproved] = useState<Approved | null>(null);
  const [loading, setLoading] = useState(true);
  const home = () => app.go({ name: "home" });

  const open = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setStep(await call("open_payout", { payout_id: payoutId }));
    } catch (reason) {
      setError(reason);
      setStep(null);
    } finally {
      setLoading(false);
    }
  }, [payoutId]);

  useEffect(() => {
    void open();
  }, [open]);

  if (approved)
    return (
      <div className="screen narrow">
        <section className="success">
          <CheckCircle size={56} weight="fill" aria-hidden />
          <h1 tabIndex={-1} ref={(node) => node?.focus()}>
            Approved and sent.
          </h1>
          <p className="lead">Clans sends the payment within a minute.</p>
          <p className="muted">
            (Clan signatures: {approved.signatures.count ?? "?"} of {approved.signatures.required ?? "?"}.)
          </p>
          <div className="actions">
            <button className="primary-button" onClick={home} autoFocus>
              Back to Home
            </button>
          </div>
        </section>
      </div>
    );

  if (loading && !step)
    return (
      <div className="screen narrow" role="status">
        <p className="quiet-line">
          <CircleNotch className="spin" size={20} aria-hidden /> Fetching the payout and checking it…
        </p>
      </div>
    );

  if (error !== null && !step)
    return (
      <div className="screen narrow">
        <PageHeading eyebrow="Payout" title="This payout couldn't be opened" />
        <Problem error={error} />
        <div className="actions">
          <button className="secondary-button" onClick={home}>
            <ArrowLeft size={18} aria-hidden /> Back to Home
          </button>
          <button className="secondary-button" onClick={() => void open()}>
            Try again
          </button>
        </div>
      </div>
    );

  if (!step) return null;

  return (
    <div className="screen narrow">
      {loading && (
        <p className="quiet-line" role="status">
          <CircleNotch className="spin" size={20} aria-hidden /> Checking the next step…
        </p>
      )}
      {step.step === "wallet" &&
        (step.wallets.length ? (
          <RegisterWallet
            key={`${step.wallets[0].clan_id}-${step.wallets[0].generation}`}
            wallet={step.wallets[0]}
            eyebrow={`${title(step.payout)} · first, the clan wallet`}
            onDone={() => void open()}
            doneLabel="Continue with this payout"
            onCancel={home}
          />
        ) : (
          <>
            <PageHeading eyebrow={title(step.payout)} title="The clan wallet isn't available" />
            <Problem
              error={{
                error:
                  "This payout needs a clan wallet that isn't registered on this laptop, and Clans doesn't list it. Nothing was signed. Check with the team",
                code: "check",
              }}
            />
            <DontApprove onHome={home} />
          </>
        ))}
      {step.step === "address" && (
        <AddressCheck key={`${step.payout.id}-${step.line}`} step={step} onConfirmed={() => void open()} onHome={home} />
      )}
      {step.step === "stopped" && (
        <>
          <PageHeading eyebrow={title(step.payout)} title="This payout can't be approved" />
          <div className="stop-box" role="alert">
            <HandPalm size={30} weight="fill" aria-hidden />
            <div>
              <h2>{sentence(step.message)}</h2>
              <p>Nothing was signed. Don't work around this; check with the clan and the team.</p>
              <div className="actions">
                <button className="secondary-button" onClick={home} autoFocus>
                  <ArrowLeft size={18} aria-hidden /> Back to Home
                </button>
              </div>
            </div>
          </div>
        </>
      )}
      {step.step === "review" && (
        <ReviewApprove key={step.review.txid} step={step} onApproved={setApproved} onReopen={() => void open()} />
      )}
    </div>
  );
}
