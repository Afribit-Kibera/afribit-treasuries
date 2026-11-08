import { useState, type ClipboardEvent, type FormEvent } from "react";
import { ArrowLeft, Key, ArrowCounterClockwise, ShieldCheck } from "@phosphor-icons/react";
import { call, isReason } from "./core";
import type { Status } from "./types";
import { Busy, CopyButton, Notice, PassphraseField, Problem } from "./ui";

const MIN_PASSPHRASE = 12;

type Stage = "welcome" | "passphrase" | "words" | "check" | "restore" | "connect" | "admin";

function pickTwo(): [number, number] {
  const random = new Uint32Array(2);
  for (;;) {
    crypto.getRandomValues(random);
    const a = random[0] % 12;
    const b = random[1] % 12;
    if (a !== b) return a < b ? [a, b] : [b, a];
  }
}

function StepRow({ step, title }: { step: number; title: string }) {
  return (
    <div className="setup-step">
      <p className="eyebrow">
        Step {step} of 4 · {title}
      </p>
      <ol className="setup-progress" aria-hidden>
        {[1, 2, 3, 4].map((n) => (
          <li key={n} className={n <= step ? "done" : ""} />
        ))}
      </ol>
    </div>
  );
}

export function Setup({ status, onDone }: { status: Status; onDone: () => void }) {
  const [stage, setStage] = useState<Stage>(status.has_key ? "connect" : "welcome");
  const [restoring, setRestoring] = useState(false);
  const [first, setFirst] = useState("");
  const [second, setSecond] = useState("");
  // The words live only here, only until the paper check passes.
  const [words, setWords] = useState<string[] | null>(null);
  const [restoreWords, setRestoreWords] = useState<string[]>(() => Array(12).fill(""));
  const [picks, setPicks] = useState<[number, number]>([0, 1]);
  const [answers, setAnswers] = useState(["", ""]);
  const [checkFailed, setCheckFailed] = useState(false);
  const [keyReady, setKeyReady] = useState(false);
  const [url, setUrl] = useState("");
  const [adminText, setAdminText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  function clearPassphrases() {
    setFirst("");
    setSecond("");
  }

  function goTo(next: Stage) {
    setError(null);
    setStage(next);
  }

  async function makeKey(event: FormEvent) {
    event.preventDefault();
    if (first.length < MIN_PASSPHRASE || first !== second || busy) return;
    setBusy(true);
    setError(null);
    const passphrase = first;
    clearPassphrases();
    try {
      if (restoring) {
        const typed = restoreWords.map((word) => word.trim().toLowerCase()).join(" ");
        await call("restore_key", { words: typed, passphrase });
        setRestoreWords(Array(12).fill(""));
        setKeyReady(true);
        setStage("connect");
      } else {
        const made = await call("create_key", { passphrase });
        setWords(made.words);
        setStage("words");
      }
    } catch (reason) {
      setError(reason);
      // Words that aren't valid: back to the boxes, keeping what they typed.
      if (restoring && isReason(reason, "bad_words")) setStage("restore");
    } finally {
      setBusy(false);
    }
  }

  function startCheck() {
    setPicks(pickTwo());
    setAnswers(["", ""]);
    setCheckFailed(false);
    goTo("check");
  }

  function checkPaper(event: FormEvent) {
    event.preventDefault();
    if (!words) return;
    const right = picks.every((n, i) => answers[i].trim().toLowerCase() === words[n]);
    setAnswers(["", ""]);
    if (!right) {
      setCheckFailed(true);
      setStage("words");
      return;
    }
    setWords(null);
    setKeyReady(true);
    goTo("connect");
  }

  function pasteWords(index: number, event: ClipboardEvent<HTMLInputElement>) {
    const pasted = event.clipboardData.getData("text").trim().split(/\s+/);
    if (pasted.length < 2) return;
    event.preventDefault();
    setRestoreWords((current) => {
      const next = [...current];
      pasted.slice(0, 12 - index).forEach((word, offset) => {
        next[index + offset] = word.toLowerCase();
      });
      return next;
    });
  }

  async function connect(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const done = await call("connect", status.default_server ? {} : { url: url.trim() });
      setAdminText(done.admin_text);
      setStage("admin");
    } catch (reason) {
      setError(reason);
    } finally {
      setBusy(false);
    }
  }

  const tooShort = first.length > 0 && first.length < MIN_PASSPHRASE;
  const mismatch = second.length > 0 && second !== first;
  const restoreComplete = restoreWords.every((word) => word.trim());

  return (
    <div className="setup">
      <div className="setup-card">
        <p className="setup-brand">
          <ShieldCheck size={26} weight="fill" aria-hidden /> Afribit Oversight
        </p>

        {stage === "welcome" && (
          <section aria-labelledby="setup-title">
            <StepRow step={1} title="Welcome" />
            <h1 id="setup-title">Set up this laptop</h1>
            <p className="lead">
              Every clan payout needs the clan's signatories and one approval from your
              community's oversight. This laptop holds that approval: an oversight key that stays
              here, locked with your passphrase.
            </p>
            <div className="choice-grid">
              <button
                className="choice"
                onClick={() => {
                  setRestoring(false);
                  goTo("passphrase");
                }}
              >
                <Key size={28} aria-hidden />
                <strong>Make a new oversight key</strong>
                <span>For a laptop that has never had one.</span>
              </button>
              <button
                className="choice"
                onClick={() => {
                  setRestoring(true);
                  goTo("restore");
                }}
              >
                <ArrowCounterClockwise size={28} aria-hidden />
                <strong>I have 12 backup words</strong>
                <span>Bring back a key you made before, from the paper.</span>
              </button>
            </div>
          </section>
        )}

        {stage === "restore" && (
          <form onSubmit={(event) => { event.preventDefault(); if (restoreComplete) goTo("passphrase"); }}>
            <StepRow step={2} title="Your 12 backup words" />
            <h1>Type your 12 backup words</h1>
            <p className="lead">Type them from your paper, in order. Each word goes in its own box.</p>
            {error !== null && <Problem error={error} />}
            <div className="word-grid word-inputs">
              {restoreWords.map((word, index) => (
                <label key={index} className="word-input">
                  <span>{index + 1}</span>
                  <input
                    aria-label={`Word ${index + 1}`}
                    value={word}
                    autoComplete="off"
                    autoCapitalize="off"
                    autoCorrect="off"
                    spellCheck={false}
                    autoFocus={index === 0}
                    onPaste={(event) => pasteWords(index, event)}
                    onChange={(event) => {
                      const next = [...restoreWords];
                      next[index] = event.target.value.replace(/\s/g, "").toLowerCase();
                      setRestoreWords(next);
                    }}
                  />
                </label>
              ))}
            </div>
            <div className="actions">
              <button type="button" className="secondary-button" onClick={() => goTo("welcome")}>
                <ArrowLeft size={18} aria-hidden /> Back
              </button>
              <button className="primary-button" disabled={!restoreComplete}>
                Next: your passphrase
              </button>
            </div>
          </form>
        )}

        {stage === "passphrase" && (
          <form onSubmit={(event) => void makeKey(event)}>
            <StepRow step={restoring ? 3 : 2} title="Your passphrase" />
            <h1>Choose a passphrase</h1>
            <p className="lead">
              Use at least {MIN_PASSPHRASE} characters. Four or five random words is a good choice.
              You'll type it each time you approve. It never leaves this laptop and can't be reset,
              so keep it somewhere safe.
            </p>
            {error !== null && <Problem error={error} />}
            <PassphraseField
              label="Passphrase"
              value={first}
              onChange={setFirst}
              autoFocus
              disabled={busy}
              hint={
                tooShort
                  ? `That's ${first.length} characters. Use at least ${MIN_PASSPHRASE}.`
                  : first.length >= MIN_PASSPHRASE
                    ? `${first.length} characters. ${first.trim().split(/\s+/).length >= 4 ? "Good: several words." : "Longer is stronger: four or five words."}`
                    : `At least ${MIN_PASSPHRASE} characters.`
              }
            />
            <PassphraseField
              label="Type it again"
              value={second}
              onChange={setSecond}
              disabled={busy}
              hint={mismatch ? "The two don't match yet." : second && second === first ? "They match." : ""}
            />
            <div className="actions">
              <button
                type="button"
                className="secondary-button"
                disabled={busy}
                onClick={() => {
                  clearPassphrases();
                  goTo(restoring ? "restore" : "welcome");
                }}
              >
                <ArrowLeft size={18} aria-hidden /> Back
              </button>
              <button
                className="primary-button"
                disabled={busy || first.length < MIN_PASSPHRASE || first !== second}
              >
                <Busy busy={busy}>{restoring ? "Restore my key" : "Make my key"}</Busy>
              </button>
            </div>
            {busy && <p className="working" role="status">Locking the key with your passphrase…</p>}
          </form>
        )}

        {stage === "words" && words && (
          <section aria-labelledby="words-title">
            <StepRow step={3} title="Your 12 backup words" />
            <h1 id="words-title">Write these on paper now</h1>
            {checkFailed ? (
              <Notice tone="warning" title="That doesn't match the words.">
                <p>Let's show them again. Check each word and its number on your paper.</p>
              </Notice>
            ) : (
              <p className="lead">Write them in order, with their numbers. They're shown only now.</p>
            )}
            <ol className="word-grid words-shown">
              {words.map((word, index) => (
                <li key={index}>
                  <span>{index + 1}</span>
                  {word}
                </li>
              ))}
            </ol>
            <Notice tone="warning">
              <p>
                Keep the paper somewhere safe, away from this laptop. Never photograph the words or
                type them anywhere else. Anyone with them can approve payouts as you.
              </p>
            </Notice>
            <div className="actions actions-end">
              <button className="primary-button" onClick={startCheck}>
                I've written them down
              </button>
            </div>
          </section>
        )}

        {stage === "check" && words && (
          <form onSubmit={checkPaper}>
            <StepRow step={3} title="Check the paper" />
            <h1>Let's check the paper</h1>
            <p className="lead">Look at your paper, not the screen.</p>
            <div className="check-words">
              {picks.map((n, i) => (
                <div className="field" key={n}>
                  <label htmlFor={`word-${n}`}>Word number {n + 1}</label>
                  <input
                    id={`word-${n}`}
                    value={answers[i]}
                    autoComplete="off"
                    autoCapitalize="off"
                    autoCorrect="off"
                    spellCheck={false}
                    autoFocus={i === 0}
                    onChange={(event) => {
                      const next = [...answers];
                      next[i] = event.target.value;
                      setAnswers(next);
                    }}
                  />
                </div>
              ))}
            </div>
            <div className="actions actions-end">
              <button className="primary-button" disabled={answers.some((a) => !a.trim())}>
                Check
              </button>
            </div>
          </form>
        )}

        {stage === "connect" && (
          <form onSubmit={(event) => void connect(event)}>
            <StepRow step={4} title="Connect to Clans" />
            <h1>Connect to Clans</h1>
            {keyReady && (
              <Notice tone="good" title="That's right. Your oversight key is ready." />
            )}
            <p className="lead">
              The laptop will see payouts that wait for you. It can't approve anything alone: each
              approval needs your passphrase.
            </p>
            {error !== null && <Problem error={error} />}
            {status.default_server ? (
              <p className="server-line">
                This app connects to <strong>{status.default_server}</strong>
              </p>
            ) : (
              <div className="field">
                <label htmlFor="clans-url">Clans address</label>
                <input
                  id="clans-url"
                  value={url}
                  placeholder="https://clans.example.org"
                  autoComplete="off"
                  spellCheck={false}
                  autoFocus
                  onChange={(event) => setUrl(event.target.value)}
                />
              </div>
            )}
            <div className="actions actions-end">
              <button
                className="primary-button"
                disabled={busy || (!status.default_server && !url.trim())}
              >
                <Busy busy={busy}>Connect</Busy>
              </button>
            </div>
          </form>
        )}

        {stage === "admin" && (
          <section aria-labelledby="admin-title">
            <StepRow step={4} title="The lines for your community" />
            <h1 id="admin-title">Send this to the Clans administrator</h1>
            <p className="lead">
              Connected. The administrator uses this to add the laptop to Clans. It holds no
              secret.
            </p>
            <pre className="admin-lines" tabIndex={0} aria-label="Lines for the administrator">
              {adminText}
            </pre>
            <div className="actions">
              <CopyButton value={adminText} label="Copy the lines" />
              <button className="primary-button" onClick={onDone}>
                Go to Home
              </button>
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
