import { useEffect, useState, type FormEvent } from "react";
import {
  startAuthentication,
  startRegistration,
} from "@simplewebauthn/browser";
import type {
  PublicKeyCredentialCreationOptionsJSON,
  PublicKeyCredentialRequestOptionsJSON,
} from "@simplewebauthn/browser";
import { api, type AccessRecovery, type Session } from "./live-api";
import { Busy, Sheet } from "./ui";
import { CopyButton } from "./CopyButton";
import { PhoneField, RegionSettings } from "./Region";

type Run = (work: () => Promise<void>) => Promise<void>;
type Options = {
  challenge_id: string;
  options: PublicKeyCredentialRequestOptionsJSON;
};
type Backup = { handle: string; recovery_codes: string[] };
type Details = { phone: string; address: string; recovery: boolean };

export function ContactFields({
  value,
  onChange,
}: {
  value: Details;
  onChange: (next: Details) => void;
}) {
  return (
    <>
      <details className="region-setup">
        <summary>Country & currency</summary>
        <RegionSettings compact />
      </details>
      <PhoneField
        value={value.phone}
        onChange={(phone) => onChange({ ...value, phone })}
      />
      <label>
        Lightning address (optional)
        <input
          name="lightning_address"
          type="text"
          inputMode="email"
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          maxLength={254}
          placeholder="yourname@blink.sv"
          value={value.address}
          onChange={(e) => onChange({ ...value, address: e.target.value })}
        />
      </label>
      <p className="field-help">
        An address from your Bitcoin wallet. You can add it later.
      </p>
      <label className="check-field">
        <input
          type="checkbox"
          checked={value.recovery}
          onChange={(e) => onChange({ ...value, recovery: e.target.checked })}
        />
        <span>Let my clan help me get back in if I lose access.</span>
      </label>
      <details className="recovery-explainer">
        <summary>How clan recovery works</summary>
        <p>
          Your clan signatories must check that it is you and approve. Then you
          wait 48 hours. Your existing account can block the request. Your phone
          number and wallet address cannot unlock your account.
        </p>
      </details>
    </>
  );
}

export function ContactEditor({
  user,
  busy,
  run,
  onRefresh,
}: {
  user: NonNullable<Session["user"]>;
  busy: boolean;
  run: Run;
  onRefresh: () => Promise<unknown>;
}) {
  const [value, setValue] = useState<Details>({
    phone: user.phone_number || "",
    address: user.lightning_address || "",
    recovery: user.clan_recovery_enabled,
  });
  const [saved, setSaved] = useState(false);
  function submit(event: FormEvent) {
    event.preventDefault();
    void run(async () => {
      const options = await api<Options>("/account/contact/options", {
        phone_number: value.phone.trim(),
        lightning_address: value.address.trim() || null,
        accepted_recovery: value.recovery,
      });
      const credential = await startAuthentication({
        optionsJSON: options.options,
      });
      await api("/account/contact/verify", {
        challenge_id: options.challenge_id,
        credential,
      });
      await onRefresh();
      setSaved(true);
    });
  }
  return (
    <section className="contact-editor">
      <h3>Your contact details</h3>
      <p className="fine-print">
        Only you can see these details. We have not checked ownership of this
        number or address. Keep your passkey and recovery words safe.
      </p>
      <form onSubmit={submit}>
        <ContactFields
          value={value}
          onChange={(next) => {
            setValue(next);
            setSaved(false);
          }}
        />
        <button className="primary-button" disabled={busy}>
          <Busy busy={busy}>Save my details</Busy>
        </button>
        {saved && <p role="status">Your details are saved.</p>}
      </form>
    </section>
  );
}

interface ClaimStatus {
  id: string;
  status: string;
  ready_at: string | null;
  expires_at: string;
  device_code: string;
  csrf: string;
}
export function ClanRecovery({
  busy,
  run,
  onBackup,
}: {
  busy: boolean;
  run: Run;
  onBackup: (kit: Backup) => Promise<void>;
}) {
  const [id, setId] = useState(
    localStorage.getItem("clans-access-request") || "",
  );
  const [state, setState] = useState<ClaimStatus | null>(null);
  const [resume, setResume] = useState(false);
  useEffect(() => {
    if (!id) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const next = await api<ClaimStatus>(`/auth/clan-recovery/${id}`);
        if (active) {
          setState(next);
          setResume(false);
        }
      } catch {
        if (active) setResume(true);
      }
      if (active) timer = setTimeout(poll, 5000);
    }
    void poll();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [id]);
  function start(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const handle = String(new FormData(event.currentTarget).get("handle"));
    void run(async () => {
      const options = await api<{
        challenge_id: string;
        request_id: string;
        options: PublicKeyCredentialCreationOptionsJSON;
      }>("/auth/clan-recovery/options", { handle });
      localStorage.setItem("clans-access-request", options.request_id);
      const credential = await startRegistration({
        optionsJSON: options.options,
      });
      const result = await api<{ request_id: string }>(
        "/auth/clan-recovery/verify",
        { challenge_id: options.challenge_id, credential },
      );
      setId(result.request_id);
    });
  }
  async function resumeRequest() {
    const options = await api<Options>("/auth/clan-recovery/resume/options", {
      request_id: id,
    });
    const credential = await startAuthentication({
      optionsJSON: options.options,
    });
    await api("/auth/clan-recovery/resume/verify", {
      challenge_id: options.challenge_id,
      credential,
    });
    setState(await api<ClaimStatus>(`/auth/clan-recovery/${id}`));
    setResume(false);
  }
  async function finish() {
    const options = await api<Options>(
      `/auth/clan-recovery/${id}/finish/options`,
      {},
      undefined,
      state!.csrf,
    );
    const credential = await startAuthentication({
      optionsJSON: options.options,
    });
    const kit = await api<Backup>(
      `/auth/clan-recovery/${id}/finish/verify`,
      { challenge_id: options.challenge_id, credential },
      undefined,
      state!.csrf,
    );
    localStorage.removeItem("clans-access-request");
    setId("");
    await onBackup(kit);
  }
  const waiting = state?.status === "waiting";
  const closed = state && !["pending", "waiting"].includes(state.status);
  return (
    <section className="clan-recovery-start">
      <h2>Ask your clan for help</h2>
      {!id ? (
        <>
          <p className="fine-print">
            Use this if you have no recovery words or spare passkey, and you
            turned on clan recovery before losing access.
          </p>
          <form onSubmit={start}>
            <label>
              Account ID
              <input
                name="handle"
                required
                autoComplete="username"
                maxLength={80}
                placeholder="clan-…"
              />
            </label>
            <button className="secondary-button" disabled={busy}>
              <Busy busy={busy}>Start clan recovery</Busy>
            </button>
          </form>
        </>
      ) : (
        <>
          {resume ? (
            <>
              <p>Use the new passkey you made for this request to check it.</p>
              <button
                className="primary-button"
                disabled={busy}
                onClick={() => void run(resumeRequest)}
              >
                Check my request
              </button>
            </>
          ) : state ? (
            <>
              <p role="status">
                {closed
                  ? "This request is closed. Use your passkey to sign in, or start again."
                  : waiting
                    ? `Your clans have approved. You can finish after ${new Date(state.ready_at!).toLocaleString()}.`
                    : "Ask the signatories in each of your clans to check that it is you. Show them this code on your new phone."}
              </p>
              {!closed && (
                <>
                  <p
                    className="device-code"
                    aria-label="Your recovery device code"
                  >
                    {state.device_code}
                  </p>
                  <CopyButton value={state.device_code} label="Copy my code" />
                  <p className="fine-print">
                    No access is given until every clan approves and the full 48
                    hours have passed. A phone number alone is not enough.
                  </p>
                </>
              )}
              {waiting && Date.parse(state.ready_at!) <= Date.now() && (
                <button
                  className="primary-button"
                  disabled={busy}
                  onClick={() => void run(finish)}
                >
                  <Busy busy={busy}>Get back into my account</Busy>
                </button>
              )}
            </>
          ) : (
            <p role="status">Checking your request…</p>
          )}
          <details>
            <summary>Request reference</summary>
            <code className="request-reference">{id}</code>
            <p className="fine-print">
              Save this reference. Keep using the new phone and passkey where
              you started.
            </p>
          </details>
          <button
            className="text-button"
            disabled={busy}
            onClick={() => {
              localStorage.removeItem("clans-access-request");
              setId("");
              setState(null);
              setResume(false);
            }}
          >
            Start a new request
          </button>
        </>
      )}
    </section>
  );
}

export function RecoveryAlerts({
  userId,
  busy,
  run,
  onRefresh,
}: {
  userId: string;
  busy: boolean;
  run: Run;
  onRefresh: () => Promise<unknown>;
}) {
  const [rows, setRows] = useState<
    { id: string; status: string; ready_at: string | null }[]
  >([]);
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const next = await api<typeof rows>("/account/access-recoveries");
        if (active) setRows(next);
      } catch {}
      if (active) timer = setTimeout(poll, 10000);
    }
    void poll();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [userId]);
  async function block(id: string) {
    const prefix = `/account/access-recoveries/${id}/block`;
    const options = await api<Options>(prefix + "/options", {});
    const credential = await startAuthentication({
      optionsJSON: options.options,
    });
    await api(prefix + "/verify", {
      challenge_id: options.challenge_id,
      credential,
    });
    setRows((value) => value.filter((row) => row.id !== id));
    await onRefresh();
  }
  if (!rows.length) return null;
  return (
    <section
      className="recovery-alert"
      role="region"
      aria-label="Account recovery warning"
    >
      <h2>Someone asked to open your account on a new phone</h2>
      <p>
        If this was not you, block it now. Your account stays yours until the
        checks and waiting time are complete.
      </p>
      {rows.map((row) => (
        <button
          key={row.id}
          className="secondary-button"
          disabled={busy}
          onClick={() => void run(() => block(row.id))}
        >
          Block this recovery request
        </button>
      ))}
    </section>
  );
}

export function RecoveryRequests({
  clanId,
  rows,
  busy,
  run,
  onRefresh,
}: {
  clanId: string;
  rows: AccessRecovery[];
  busy: boolean;
  run: Run;
  onRefresh: () => Promise<unknown>;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [checked, setChecked] = useState(false);
  const row = rows.find((item) => item.id === selected);
  async function approve() {
    const prefix = `/clans/${clanId}/access-recoveries/${row!.id}/approval`;
    const options = await api<Options>(prefix + "/options", {
      device_code: code.trim(),
      member_checked: checked,
    });
    const credential = await startAuthentication({
      optionsJSON: options.options,
    });
    await api(prefix + "/verify", {
      challenge_id: options.challenge_id,
      credential,
    });
    setSelected(null);
    await onRefresh();
  }
  if (!rows.length) return null;
  return (
    <section className="recovery-requests">
      <h3>Help a member get back in</h3>
      {rows.map((item) => (
        <div className="setup-note" key={item.id}>
          <div>
            <strong>{item.member_name}</strong>
            <p>
              {item.approvals} of {item.required} signatories approved.
            </p>
            {item.approved_names.length > 0 && (
              <p>Approved by {item.approved_names.join(", ")}.</p>
            )}
            {item.can_approve && (
              <button
                className="text-button"
                disabled={busy}
                onClick={() => {
                  setSelected(item.id);
                  setCode("");
                  setChecked(false);
                }}
              >
                Check recovery request
              </button>
            )}
          </div>
        </div>
      ))}
      {row && (
        <Sheet
          title={`Help ${row.member_name} get back in`}
          busy={busy}
          onClose={() => {
            if (!busy) setSelected(null);
          }}
        >
          <p>
            Meet {row.member_name}, or call them using a contact you already
            trust. Check the code on their new phone before approving.
          </p>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void run(approve);
            }}
          >
            <label>
              Code on the member's new phone
              <input
                value={code}
                onChange={(event) => setCode(event.target.value)}
                autoComplete="off"
                autoCapitalize="characters"
                spellCheck={false}
                required
                maxLength={20}
                placeholder="A1B2-C3D4-E5F6"
              />
            </label>
            <label className="check-field">
              <input
                type="checkbox"
                checked={checked}
                onChange={(event) => setChecked(event.target.checked)}
                required
              />
              <span>
                I checked that this is {row.member_name} and matched the code.
              </span>
            </label>
            <p className="fine-print">
              Every affected clan must approve. Then there is a 48-hour wait.
              This does not approve a payment.
            </p>
            <button className="primary-button" disabled={busy || !checked}>
              <Busy busy={busy}>Approve account recovery</Busy>
            </button>
          </form>
        </Sheet>
      )}
    </section>
  );
}
