import {
  useCallback,
  useEffect,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  startAuthentication,
  startRegistration,
} from "@simplewebauthn/browser";
import type {
  PublicKeyCredentialCreationOptionsJSON,
  PublicKeyCredentialRequestOptionsJSON,
} from "@simplewebauthn/browser";
import {
  ArrowRight,
  ArrowLeft,
  Check,
  DownloadSimple,
  Fingerprint,
  House,
  UsersThree,
  ListBullets,
  UserCircle,
  Plus,
  Sun,
  Moon,
  ShieldCheck,
  Stack,
  SignOut,
  ArrowClockwise,
  Link,
  CheckCircle,
  WarningCircle,
} from "@phosphor-icons/react";
import {
  api,
  getSession,
  type Session,
  type ClanDetail,
  type Grant,
  type Deposit,
  type ActivityItem,
} from "./live-api";
import { Avatar, Sheet, Busy, satsLabel, useScreenStart } from "./ui";
import { DepositSheet, GrantMoney } from "./MoneyFlows";
import { owedLabel } from "./grant-debt";
import { useClanWallet } from "./useClanWallet";
import {
  ContactFields,
  ContactEditor,
  ClanRecovery,
  RecoveryAlerts,
  RecoveryRequests,
} from "./AccountAccess";
import { InstallControl } from "./PwaInstall";
import { CopyButton } from "./CopyButton";
import { FeedbackContext } from "./ui";
import { HomeDashboard } from "./HomeDashboard";
import { GrantRequest } from "./GrantRequest";
import { RegionSettings } from "./Region";
import { ProfileScreens } from "./ProfileScreens";
import { ActivityScreen } from "./ActivityScreen";
import { ActivityDetailSheet, ActivityPaymentSheet } from "./ActivityDetail";
import { ClanScreen } from "./ClanScreen";

type Tab = "home" | "clan" | "activity" | "profile";
type Modal =
  | "create"
  | "join"
  | "invite"
  | "request"
  | "switch"
  | "money"
  | "vote"
  | "repay"
  | null;
type Backup = { handle: string; recovery_codes: string[] };
const statusLabels: Record<string, string> = {
  voting: "Voting",
  awaiting_acceptance: "Member to accept",
  awaiting_funding: "Ready for an invoice",
  awaiting_signatures: "Waiting for signatories",
  payment_queued: "Payment queued",
  paying: "Payment in progress",
  in_recovery: "To be repaid",
  recovered: "Repaid",
  rejected: "Not approved",
  cancelled: "Withdrawn",
};
// Titles for an older server only. Current servers send every item's title.
const eventLabels: Record<string, string> = {
  clan_created: "Created the clan",
  invitation_created: "Invited a member",
  invitation_revoked: "Cancelled an invitation",
  member_joined: "Joined the clan",
  grant_requested: "Asked for a grant",
  grant_vote_cast: "Voted on a grant",
  grant_accepted: "Accepted the grant terms",
  grant_cancelled: "Withdrew a grant request",
  deposit_requested: "Asked for a payment address",
  deposit_received: "Money received",
  repayment_received: "Repayment received",
  payment_destination_set: "Added a wallet request",
  payment_approved: "Approved a payment",
  grant_disbursed: "Grant paid",
  treasury_settled: "Money received",
};

export default function LiveApp() {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState<Tab>("home");
  useScreenStart(tab);
  const [clan, setClan] = useState<ClanDetail | null>(null);
  const clanWallet = useClanWallet(clan?.id || "");
  const walletActive =
    !!clanWallet.view?.enabled && clanWallet.view.status === "active";
  const paymentReady = walletActive || !!clan?.treasury_ready;
  // Money can come in through the clan wallet, or through Lightning when that's on.
  const canReceive =
    walletActive ||
    (!!session?.capabilities.receiving && !!clan?.treasury_ready);
  const needsGrantAction = (item: Grant) =>
    item.can_vote ||
    !!item.payment?.can_approve ||
    (walletActive &&
      ((item.beneficiary_id === session?.user?.id &&
        [
          "awaiting_acceptance",
          "awaiting_funding",
          "awaiting_signatures",
        ].includes(item.status)) ||
        (!!clan?.my_signer && item.status === "awaiting_signatures")));
  const [selected, setSelected] = useState(
    localStorage.getItem("clans-active") || "",
  );
  const [modal, setModal] = useState<Modal>(null);
  const [requestKey, setRequestKey] = useState(() => crypto.randomUUID());
  useEffect(() => {
    setRequestKey(crypto.randomUUID());
    if (modal !== "invite") setInviteLink("");
  }, [modal]);
  const [auth, setAuth] = useState<
    "welcome" | "register" | "passkey" | "recover"
  >("welcome");
  const [displayName, setDisplayName] = useState("");
  const [username, setUsername] = useState("");
  const [contact, setContact] = useState({
    phone: "",
    address: "",
    recovery: false,
  });
  useEffect(() => {
    function resize() {
      const viewport = window.visualViewport;
      document.documentElement.style.setProperty(
        "--visible-height",
        `${viewport && viewport.scale === 1 ? viewport.height : innerHeight}px`,
      );
      document.documentElement.style.setProperty(
        "--viewport-bottom",
        `${Math.max(0, innerHeight - (viewport?.height || innerHeight) - (viewport?.offsetTop || 0))}px`,
      );
    }
    resize();
    window.visualViewport?.addEventListener("resize", resize);
    window.visualViewport?.addEventListener("scroll", resize);
    window.addEventListener("resize", resize);
    return () => {
      window.visualViewport?.removeEventListener("resize", resize);
      window.visualViewport?.removeEventListener("scroll", resize);
      window.removeEventListener("resize", resize);
    };
  }, []);
  const [backup, setBackup] = useState<Backup | null>(null);
  const [savedBackup, setSavedBackup] = useState(false);
  const [theme, setTheme] = useState(
    document.documentElement.dataset.theme || "dark",
  );
  const [pendingInvite, setPendingInvite] = useState(() => {
    const incoming =
      location.pathname === "/join" ? location.hash.slice(1) : "";
    if (incoming) {
      sessionStorage.setItem("clans-invite", incoming);
      history.replaceState(null, "", "/join");
    }
    return incoming || sessionStorage.getItem("clans-invite") || "";
  });
  const [inviteInfo, setInviteInfo] = useState<{
    name: string;
    is_signer: boolean;
    invited_by: string;
    custody_notice: string;
  } | null>(null);
  const [inviteLink, setInviteLink] = useState("");
  const [openedGrant, setGrant] = useState<Grant | null>(null);
  const [deposit, setDeposit] = useState<{
    grantId?: string;
    existing?: Deposit;
  } | null>(null);
  const grant =
    clan?.grants.find((item) => item.id === openedGrant?.id) || null;
  const [activityItem, setActivityItem] = useState<ActivityItem | null>(null);
  const [activityPayment, setActivityPayment] = useState<{
    id: string;
    grantId?: string;
  } | null>(null);
  useEffect(() => {
    setActivityItem(null);
    setActivityPayment(null);
  }, [clan?.id]);
  const [security, setSecurity] = useState<{
    recovery_codes_remaining: number;
    passkeys: { id: string; label: string; backed_up: boolean }[];
  } | null>(null);

  useEffect(() => {
    if (!clan || !session?.user) return;
    const params = new URLSearchParams(location.search),
      id = params.get("payment");
    if (!id || !/^[a-f0-9-]{36}$/.test(id)) return;
    let active = true;
    void api<Deposit>(`/clans/${clan.id}/deposits/${id}`)
      .then((row) => {
        if (active)
          setDeposit({ existing: row, grantId: row.grant_id || undefined });
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    params.delete("payment");
    params.delete("clan");
    history.replaceState(
      null,
      "",
      location.pathname + (params.size ? "?" + params : "") + location.hash,
    );
    return () => {
      active = false;
    };
  }, [clan?.id, session?.user?.id]);
  const refresh = useCallback(async (wanted?: string) => {
    const next = await getSession();
    setSession(next);
    if (next.user) {
      const id =
        wanted ||
        new URLSearchParams(location.search).get("clan") ||
        localStorage.getItem("clans-active") ||
        next.clans?.[0]?.id;
      const active = next.clans?.find((c) => c.id === id) || next.clans?.[0];
      if (active) {
        const detail = await api<ClanDetail>(
          `/clans/${active.id}?include_activity=false`,
        );
        setClan(detail);
        setGrant((current) =>
          current
            ? detail.grants.find((item) => item.id === current.id) || null
            : null,
        );
        setSelected(active.id);
        localStorage.setItem("clans-active", active.id);
      } else {
        setClan(null);
        setSelected("");
      }
    } else setClan(null);
    return next;
  }, []);
  useEffect(() => {
    refresh()
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
    const expired = () => {
      setSession(null);
      setClan(null);
      setGrant(null);
      setDeposit(null);
      setModal(null);
      setActivityItem(null);
      setActivityPayment(null);
      setNotice("Your session expired. Sign in again to continue.");
    };
    window.addEventListener("clans-session-expired", expired);
    return () => window.removeEventListener("clans-session-expired", expired);
  }, [refresh]);
  useEffect(() => {
    if (!selected || !session?.user || busy) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const next = await api<ClanDetail>(
          `/clans/${selected}?include_activity=false`,
        );
        if (active) {
          setClan(next);
          setGrant((current) =>
            current
              ? next.grants.find((item) => item.id === current.id) || null
              : null,
          );
        }
      } catch {
        /* Explicit actions report failures; polling retries quietly. */
      }
      if (active) timer = setTimeout(poll, 5000);
    }
    timer = setTimeout(poll, 5000);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [selected, session?.user?.id, busy]);
  useEffect(() => {
    if (pendingInvite)
      api<typeof inviteInfo>("/invitations/preview", { token: pendingInvite })
        .then(setInviteInfo)
        .catch((e) => {
          setError(e.message);
          setInviteInfo(null);
        });
    else setInviteInfo(null);
  }, [pendingInvite]);
  useEffect(() => {
    if (tab === "profile" && session?.user)
      api<typeof security>("/account/security")
        .then(setSecurity)
        .catch((e) => setError(e.message));
  }, [tab, session?.user?.id]);

  async function run(work: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await work();
    } catch (e) {
      setError(
        e instanceof Error && e.name !== "NotAllowedError"
          ? e.message
          : "The passkey request was cancelled. You can try again.",
      );
    } finally {
      setBusy(false);
    }
  }
  function toggleTheme() {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.dataset.theme = next;
    localStorage.setItem("clans-theme", next);
  }
  async function login() {
    const data = await api<{
      challenge_id: string;
      options: PublicKeyCredentialRequestOptionsJSON;
    }>("/auth/login/options", {});
    const credential = await startAuthentication({ optionsJSON: data.options });
    await api("/auth/login/verify", {
      challenge_id: data.challenge_id,
      credential,
    });
    await refresh();
  }
  function register(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setDisplayName(String(form.get("name") || "").trim());
    setUsername(
      String(form.get("username") || "")
        .trim()
        .toLowerCase(),
    );
    setAuth("passkey");
  }
  async function createPasskey() {
    await run(async () => {
      const data = await api<{
        challenge_id: string;
        options: PublicKeyCredentialCreationOptionsJSON;
      }>("/auth/register/options", {
        display_name: displayName,
        username,
        accepted_terms: true,
        phone_number: contact.phone.trim(),
        lightning_address: contact.address.trim() || null,
        accepted_recovery: contact.recovery,
      });
      const credential = await startRegistration({ optionsJSON: data.options });
      const result = await api<Backup>("/auth/register/verify", {
        challenge_id: data.challenge_id,
        credential,
      });
      setBackup(result);
      setSavedBackup(false);
      await refresh();
    });
  }
  async function recover(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await run(async () => {
      const data = await api<{
        challenge_id: string;
        options: PublicKeyCredentialCreationOptionsJSON;
      }>("/auth/recover/options", {
        handle: form.get("handle"),
        code: form.get("code"),
      });
      const credential = await startRegistration({ optionsJSON: data.options });
      const result = await api<Backup>("/auth/recover/verify", {
        challenge_id: data.challenge_id,
        credential,
      });
      setBackup(result);
      setSavedBackup(false);
      await refresh();
    });
  }
  async function secureAction(
    action: "add_passkey" | "recovery_codes" | "username",
    username?: string,
  ) {
    await run(async () => {
      const opts = await api<{
        challenge_id: string;
        options: PublicKeyCredentialRequestOptionsJSON;
      }>("/account/reauth/options", {
        action,
        ...(username ? { username } : {}),
      });
      const credential = await startAuthentication({
        optionsJSON: opts.options,
      });
      const result = await api<
        | Backup
        | {
            challenge_id: string;
            options: PublicKeyCredentialCreationOptionsJSON;
          }
      >("/account/reauth/verify", {
        challenge_id: opts.challenge_id,
        credential,
      });
      if (action === "username") {
        await refresh();
        setNotice("Username saved. Your clan and grants stay the same.");
      } else if ("recovery_codes" in result) {
        setBackup(result);
        setSavedBackup(false);
      } else {
        const nextCredential = await startRegistration({
          optionsJSON: result.options,
        });
        await api("/account/passkeys/verify", {
          challenge_id: result.challenge_id,
          credential: nextCredential,
        });
        setNotice("Your additional passkey is ready.");
        setSecurity(await api("/account/security"));
      }
    });
  }
  function downloadBackup() {
    if (!backup) return;
    const blob = new Blob(
      [
        `AfriBit Clans recovery kit\nWebsite: ${location.origin}\nUsername: ${backup.handle}\n\nKeep these words private and in order. Use them once to get back into Clans. They replace your old passkeys and sign out other devices. Your clan and repayments stay the same. These words are not a Bitcoin wallet backup.\n\n${backup.recovery_codes.join("\n")}\n`,
      ],
      { type: "text/plain;charset=utf-8" },
    );
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "afribit-clans-recovery.txt";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  async function finishBackup() {
    await api("/onboarding/complete", {});
    setBackup(null);
    setAuth("welcome");
    await refresh();
  }
  function chooseClan(id: string) {
    setSelected(id);
    localStorage.setItem("clans-active", id);
    setModal(null);
    setTab("home");
    void run(async () => {
      await refresh(id);
    });
  }
  const custody = <p className="custody-copy">{session?.custody_notice}</p>;
  const profileView = session?.user ? (
    <ProfileScreens
      name={session.user!.display_name}
      username={session.user!.handle}
      busy={busy}
      logout={() =>
        void run(async () => {
          await api("/auth/logout", {});
          setTab("home");
          await refresh();
        })
      }
    >
      {(page) =>
        page === "details" ? (
          <>
            <AccountInfo
              view="details"
              session={session}
              secureAction={secureAction}
              security={security}
              busy={busy}
              logout={() => {}}
            />
            <ContactEditor
              key={session.user!.id}
              user={session.user!}
              busy={busy}
              run={run}
              onRefresh={refresh}
            />
          </>
        ) : page === "security" || page === "limits" ? (
          <AccountInfo
            view={page}
            session={session}
            secureAction={secureAction}
            security={security}
            busy={busy}
            logout={() => {}}
          />
        ) : page === "region" ? (
          <RegionSettings />
        ) : page === "install" ? (
          <InstallControl />
        ) : (
          <>
            <p className="policy-note">
              You can belong to one clan at a time. Your grants and repayments
              stay with your account when you change your passkey or recovery
              words.
            </p>
            {custody}
          </>
        )
      }
    </ProfileScreens>
  ) : null;
  const close = () => {
    if (!busy) {
      setModal(null);
      setGrant(null);
      setDeposit(null);
    }
  };
  const primary = (label: string, action: () => void, icon?: ReactNode) => (
    <button className="primary-button" disabled={busy} onClick={action}>
      <Busy busy={busy}>{label}</Busy>
      {icon}
    </button>
  );

  return (
    <FeedbackContext.Provider value={error}>
      <div
        className={`app live-app ${clan && !backup ? (tab === "home" ? "home-screen" : tab === "activity" ? "activity-screen" : "") : ""}`}
      >
        <div className="background-art" aria-hidden="true" />
        <div className="app-shell">
          <header className="app-header">
            <a className="brand" href="/" aria-label="AfriBit Clans home">
              <img src="/assets/afribit-mark.webp" alt="" />
              <span className="brand-divider" />
              <span className="wordmark">
                Afri<span>₿</span>it <em>Clans</em>
              </span>
            </a>
            <div className="header-actions">
              <button
                className="icon-button"
                aria-label={
                  theme === "dark"
                    ? "Switch to light mode"
                    : "Switch to dark mode"
                }
                onClick={toggleTheme}
              >
                {theme === "dark" ? <Sun size={23} /> : <Moon size={23} />}
              </button>
              {session?.user && (
                <button
                  className="icon-button"
                  aria-label="Refresh account"
                  disabled={busy}
                  onClick={() =>
                    run(async () => {
                      await refresh();
                      setNotice("Account refreshed.");
                    })
                  }
                >
                  <ArrowClockwise size={22} />
                </button>
              )}
            </div>
          </header>
          {error && (
            <div className="live-alert error" role="alert">
              <WarningCircle size={20} />
              <span>{error}</span>
              <button aria-label="Dismiss error" onClick={() => setError("")}>
                ×
              </button>
            </div>
          )}
          {notice && (
            <div className="live-alert" role="status">
              <CheckCircle size={20} />
              <span>{notice}</span>
              <button
                aria-label="Dismiss message"
                onClick={() => setNotice("")}
              >
                ×
              </button>
            </div>
          )}
          {session?.user && (
            <RecoveryAlerts
              userId={session.user.id}
              busy={busy}
              run={run}
              onRefresh={refresh}
            />
          )}
          {loading ? (
            <main className="loading-state">
              <Stack className="pulse" size={36} />
              <p>Opening your account...</p>
            </main>
          ) : backup ? (
            <main className="onboarding backup-page">
              <Step n={3} label="Protect your account" />
              <ShieldCheck className="welcome-icon" size={46} />
              <h1>
                Your way
                <br />
                back in.
              </h1>
              <p className="lead">
                Write these 12 words on paper, in order. Keep the paper
                somewhere private. Use them with your username if you lose
                access to your phone.
              </p>
              <label>
                Username
                <input readOnly value={backup.handle} />
              </label>
              <div className="recovery-grid">
                {backup.recovery_codes[0].split(" ").map((word, index) => (
                  <div className="recovery-word" key={index}>
                    <span>{index + 1}</span>
                    <strong>{word}</strong>
                  </div>
                ))}
              </div>
              <button className="secondary-button" onClick={downloadBackup}>
                <DownloadSimple size={19} />
                Download a backup (optional)
              </button>
              <p className="fine-print">
                You can continue after writing them down. No download is needed
                to join a clan.
              </p>
              <p className="fine-print">
                Anyone with your username and these words can access your
                account. Never share them, even with a clan signatory. They are
                for Clans only, not for restoring a Bitcoin wallet.
              </p>
              <label className="check-field">
                <input
                  type="checkbox"
                  checked={savedBackup}
                  onChange={(e) => setSavedBackup(e.target.checked)}
                />
                <span>I saved my username and 12 words.</span>
              </label>
              <button
                className="primary-button"
                disabled={!savedBackup || busy}
                onClick={() => run(finishBackup)}
              >
                <Busy busy={busy}>
                  {pendingInvite
                    ? "Continue to invitation"
                    : "Continue to my account"}
                </Busy>
                <ArrowRight />
              </button>
            </main>
          ) : !session?.user ? (
            <main className="onboarding welcome-page">
              {auth === "welcome" ? (
                <>
                  <h1>
                    Stronger
                    <br />
                    <em>in a circle.</em>
                  </h1>
                  <p className="lead">
                    Save together. Decide together. Capital that comes back to
                    help the next person grow.
                  </p>
                  <div className="welcome-seal">
                    <UsersThree size={34} weight="duotone" />
                    <div>
                      <strong>Your people. Your purpose.</strong>
                      <span>Shared money, built on Bitcoin.</span>
                    </div>
                  </div>
                  {inviteInfo && (
                    <div className="invite-preview">
                      <span className="eyebrow">You’re invited</span>
                      <h2>{inviteInfo.name}</h2>
                      <p>
                        {inviteInfo.invited_by} invited you as{" "}
                        {inviteInfo.is_signer ? "a signatory" : "a member"}.
                        Create an account or sign in to review and accept.
                      </p>
                    </div>
                  )}
                  {primary(
                    "Create my account",
                    () => setAuth("register"),
                    <ArrowRight size={20} />,
                  )}
                  <button
                    className="secondary-button"
                    disabled={busy}
                    onClick={() => run(login)}
                  >
                    <Fingerprint size={22} />
                    <Busy busy={busy}>Sign in with a passkey</Busy>
                  </button>
                  <button
                    className="text-button recovery-link"
                    onClick={() => setAuth("recover")}
                  >
                    Lost access? Recover your account
                  </button>
                  <p className="fine-print launch-note">
                    Clans is a feature of Afribit Wallet.{" "}
                    <a href="/about/">See how it works</a>.
                  </p>
                  <InstallControl />
                </>
              ) : auth === "register" ? (
                <>
                  <button
                    className="back-button"
                    onClick={() => setAuth("welcome")}
                  >
                    <ArrowLeft size={18} />
                    Back
                  </button>
                  <Step n={1} label="Meet your clan" />
                  <h1>
                    Start with
                    <br />
                    <em>you.</em>
                  </h1>
                  <p className="lead">
                    Create your own account first. Joining a clan is always your
                    choice.
                  </p>
                  <form onSubmit={register}>
                    <label>
                      Your name
                      <input
                        name="name"
                        defaultValue={displayName}
                        required
                        minLength={2}
                        maxLength={100}
                        autoComplete="name"
                        placeholder="How should your clan know you?"
                      />
                    </label>
                    <label>
                      Choose a username
                      <input
                        name="username"
                        value={username}
                        onChange={(event) =>
                          setUsername(event.target.value.toLowerCase())
                        }
                        required
                        minLength={3}
                        maxLength={24}
                        pattern="[a-z][a-z0-9_]{2,23}"
                        autoComplete="username"
                        autoCapitalize="none"
                        spellCheck={false}
                        placeholder="e.g. amina23"
                      />
                    </label>
                    <p className="field-help">
                      Use 3 to 24 letters, numbers or underscores. Start with a
                      letter. This belongs to you, not your clan.
                    </p>
                    <ContactFields value={contact} onChange={setContact} />
                    <div className="setup-note">
                      <Fingerprint size={29} />
                      <div>
                        <strong>Step 2 · Create a passkey</strong>
                        <p>
                          Use your fingerprint, face unlock or device PIN. Your
                          device keeps the passkey.
                        </p>
                      </div>
                    </div>
                    <label className="check-field">
                      <input name="terms" type="checkbox" required />
                      <span>
                        I agree to create an account and understand that I’m
                        responsible for keeping my passkey and recovery words
                        safe. My name is visible to clans I join.
                      </span>
                    </label>
                    <button className="primary-button" disabled={busy}>
                      Continue to security
                      <ArrowRight size={21} />
                    </button>
                  </form>
                  <p className="fine-print">
                    Next: save your recovery words, then create a clan or accept
                    an invitation. No payment is required to create an account.
                  </p>
                </>
              ) : auth === "passkey" ? (
                <>
                  <button
                    className="back-button"
                    onClick={() => setAuth("register")}
                  >
                    <ArrowLeft size={18} />
                    Back
                  </button>
                  <Step n={2} label="Secure your account" />
                  <Fingerprint className="welcome-icon" size={46} />
                  <h1>
                    Your key.
                    <br />
                    <em>Your control.</em>
                  </h1>
                  <p className="lead">
                    Welcome, {displayName}. Protect your account with a passkey:
                    fingerprint, face unlock or your device PIN.
                  </p>
                  <div className="setup-note">
                    <ShieldCheck size={28} />
                    <div>
                      <strong>No password to remember.</strong>
                      <p>
                        Your device or password manager keeps your passkey.
                        Next, we will give you 12 recovery words to keep safe.
                      </p>
                    </div>
                  </div>
                  <button
                    className="primary-button"
                    disabled={busy}
                    onClick={createPasskey}
                  >
                    <Busy busy={busy}>Create my passkey</Busy>
                    <Fingerprint size={21} />
                  </button>
                  <p className="fine-print">
                    You can add a passkey from another device later in your
                    account settings.
                  </p>
                </>
              ) : (
                <>
                  <button
                    className="back-button"
                    onClick={() => setAuth("welcome")}
                  >
                    <ArrowLeft size={18} />
                    Back
                  </button>
                  <ShieldCheck className="welcome-icon" size={42} />
                  <h1>
                    Find your
                    <br />
                    <em>way back.</em>
                  </h1>
                  <p className="lead">
                    Enter your 12 words to set up access on this device. This
                    signs out your other devices. Your clan and repayments stay
                    the same.
                  </p>
                  <form onSubmit={recover}>
                    <label>
                      Username
                      <input
                        name="handle"
                        required
                        autoComplete="username"
                        placeholder="Your username or older account ID"
                        maxLength={80}
                      />
                    </label>
                    <label>
                      Your 12 recovery words
                      <textarea
                        name="code"
                        rows={3}
                        autoCapitalize="none"
                        required
                        autoComplete="off"
                        spellCheck={false}
                        maxLength={200}
                      />
                    </label>
                    <p className="field-help">
                      An older recovery code works here too.
                    </p>
                    <button className="primary-button" disabled={busy}>
                      <Busy busy={busy}>Create replacement passkey</Busy>
                      <Fingerprint size={21} />
                    </button>
                  </form>
                  <ClanRecovery
                    busy={busy}
                    run={run}
                    onBackup={async (kit) => {
                      setBackup(kit);
                      setSavedBackup(false);
                      await refresh();
                    }}
                  />
                </>
              )}
            </main>
          ) : !session.user.contact_complete ? (
            <main className="onboarding">
              <h1>Your details</h1>
              <p className="lead">
                Add a private phone number before using your clan.
              </p>
              <ContactEditor
                user={session.user}
                busy={busy}
                run={run}
                onRefresh={refresh}
              />
            </main>
          ) : !clan ? (
            tab === "profile" ? (
              <main className="main-content page-profile">
                {profileView}
                <button className="text-button" onClick={() => setTab("home")}>
                  <ArrowLeft />
                  Back to setup
                </button>
              </main>
            ) : (
              <main className="onboarding">
                <Step n={4} label="Find your people" />
                <h1>
                  Welcome,
                  <br />
                  <em>{session.user.display_name.split(" ")[0]}.</em>
                </h1>
                <p className="lead">
                  Your account is ready. Start a new circle or accept an
                  invitation to an existing clan.
                </p>
                {inviteInfo && pendingInvite ? (
                  <InviteAcceptance
                    info={inviteInfo}
                    busy={busy}
                    onAccept={(signer) =>
                      run(async () => {
                        const result = await api<{ clan_id: string }>(
                          "/invitations/accept",
                          {
                            token: pendingInvite,
                            accepted_custody: true,
                            accepted_signer: signer,
                          },
                        );
                        setPendingInvite("");
                        sessionStorage.removeItem("clans-invite");
                        await refresh(result.clan_id);
                        setNotice("You joined the clan.");
                      })
                    }
                  />
                ) : null}
                {primary(
                  "Create a clan",
                  () => setModal("create"),
                  <Plus size={22} />,
                )}
                <button
                  className="secondary-button"
                  onClick={() => setModal("join")}
                >
                  <Link size={20} />I have an invitation
                </button>
                <button
                  className="text-button recovery-link"
                  onClick={() => setTab("profile")}
                >
                  My account & security
                </button>
              </main>
            )
          ) : (
            <>
              <main
                key={tab}
                id="main-content"
                className={`main-content page-${tab}`}
              >
                <div className="page-heading home-heading-hidden">
                  <div>
                    <div className="clan-title-row">
                      <div className="clan-title">
                        <h1>{clan.name}</h1>
                      </div>
                      <span
                        className={`status-pill ${clan.governance_ready ? "" : "setup-pill"}`}
                      >
                        <span />
                        {clan.governance_ready ? "Ready" : "Setting up"}
                      </span>
                    </div>
                    <p>
                      {clan.description || "Shared money to help your members."}
                    </p>
                  </div>
                </div>
                {pendingInvite && inviteInfo && (
                  <div className="invite-preview">
                    <p>
                      Invitation to <strong>{inviteInfo.name}</strong>
                    </p>
                    <button
                      className="text-button"
                      onClick={() => setModal("join")}
                    >
                      Review invitation <ArrowRight />
                    </button>
                  </div>
                )}
                {tab === "home" ? (
                  <>
                    <HomeDashboard
                      clan={clan}
                      request={() => setModal("request")}
                      repay={() => setModal("repay")}
                      vote={() => setModal("vote")}
                      activity={() => setTab("activity")}
                      members={() => setTab("clan")}
                      paymentReady={paymentReady}
                      attentionCount={
                        clan.grants.filter(needsGrantAction).length
                      }
                    />
                    {clan.deposits
                      .filter(
                        (d) =>
                          d.requested_by_me &&
                          !["settled", "expired", "failed"].includes(d.status),
                      )
                      .slice(0, 3)
                      .map((d) => (
                        <button
                          className="pending-payment text-button"
                          key={d.id}
                          onClick={() =>
                            setDeposit({
                              existing: d,
                              grantId: d.grant_id || undefined,
                            })
                          }
                        >
                          Continue {d.grant_id ? "repayment" : "payment"} -{" "}
                          {satsLabel(d.amount_sats)} <ArrowRight size={18} />
                        </button>
                      ))}
                  </>
                ) : tab === "clan" ? (
                  <>
                    <RecoveryRequests
                      clanId={clan.id}
                      rows={clan.access_recoveries || []}
                      busy={busy}
                      run={run}
                      onRefresh={refresh}
                    />
                    <ClanScreen
                      key={clan.id}
                      clan={clan}
                      userId={session.user!.id}
                      busy={busy}
                      invite={() => setModal("invite")}
                      revoke={(id) =>
                        void run(async () => {
                          await api(
                            `/clans/${selected}/invitations/${id}/revoke`,
                            {},
                          );
                          await refresh();
                          setNotice("Invitation cancelled.");
                        })
                      }
                    />
                  </>
                ) : tab === "activity" ? (
                  <ActivityScreen
                    key={clan.id}
                    clanId={clan.id}
                    clanName={clan.name}
                    labels={eventLabels}
                    onOpen={setActivityItem}
                    pending={
                      <>
                        {clan.grants.some(needsGrantAction) ? (
                          <details className="activity-pending">
                            <summary>Requests waiting for you</summary>
                            {clan.grants.filter(needsGrantAction).map((g) => (
                              <GrantCard
                                key={g.id}
                                grant={g}
                                busy={busy}
                                open={() => setGrant(g)}
                              />
                            ))}
                          </details>
                        ) : null}
                        <GrantHistory
                          grants={clan.grants}
                          busy={busy}
                          open={setGrant}
                        />
                      </>
                    }
                  />
                ) : (
                  profileView
                )}
              </main>
              <nav className="bottom-nav" aria-label="Main navigation">
                <Nav
                  label="Home"
                  active={tab === "home"}
                  action={() => setTab("home")}
                  icon={<House />}
                />
                <Nav
                  label="Clan"
                  active={tab === "clan"}
                  action={() => setTab("clan")}
                  icon={<UsersThree />}
                />
                <button
                  className="create-button"
                  aria-label="Add money"
                  disabled={!canReceive}
                  onClick={() => setDeposit({})}
                >
                  <Plus size={29} />
                </button>
                <Nav
                  label="Activity"
                  active={tab === "activity"}
                  action={() => setTab("activity")}
                  icon={<ListBullets />}
                />
                <Nav
                  label="Profile"
                  active={tab === "profile"}
                  action={() => setTab("profile")}
                  icon={<UserCircle />}
                />
              </nav>
            </>
          )}
        </div>
        {modal === "create" && (
          <Sheet
            title="A circle with purpose."
            eyebrow="Create your clan · 1 of 2"
            onClose={close}
            busy={busy}
          >
            <CreateClan
              busy={busy}
              custody={session?.custody_notice || ""}
              onSubmit={(data) =>
                run(async () => {
                  const result = await api<{ clan_id: string }>(
                    "/clans",
                    data,
                    requestKey,
                  );
                  setModal(null);
                  setTab("home");
                  await refresh(result.clan_id);
                  setNotice(
                    "Clan created. Invite your members to complete setup.",
                  );
                })
              }
            />
          </Sheet>
        )}
        {modal === "join" && (
          <Sheet
            title="An invitation to belong."
            eyebrow="Join a clan"
            onClose={close}
            busy={busy}
          >
            {inviteInfo && pendingInvite ? (
              <InviteAcceptance
                info={inviteInfo}
                busy={busy}
                onAccept={(signer) =>
                  run(async () => {
                    const result = await api<{ clan_id: string }>(
                      "/invitations/accept",
                      {
                        token: pendingInvite,
                        accepted_custody: true,
                        accepted_signer: signer,
                      },
                    );
                    setPendingInvite("");
                    sessionStorage.removeItem("clans-invite");
                    setModal(null);
                    await refresh(result.clan_id);
                    setNotice("Membership accepted.");
                  })
                }
              />
            ) : (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  const value = String(
                    new FormData(e.currentTarget).get("link") || "",
                  ).trim();
                  let token = value;
                  try {
                    token = new URL(value).hash.slice(1);
                  } catch {
                    /* Accept a privately shared token too. */
                  }
                  if (token.length < 32 || token.length > 100) {
                    setError("Paste the complete invitation link.");
                    return;
                  }
                  sessionStorage.setItem("clans-invite", token);
                  setPendingInvite(token);
                }}
              >
                <p className="lead">
                  Paste the private invitation link shared by your clan
                  organizer.
                </p>
                <label>
                  Invitation link
                  <input name="link" required type="text" autoComplete="off" />
                </label>
                <button className="primary-button">
                  Review invitation
                  <ArrowRight />
                </button>
              </form>
            )}
          </Sheet>
        )}
        {modal === "invite" && clan && (
          <Sheet
            title="Invite a member"
            eyebrow="Private invitation"
            onClose={close}
            busy={busy}
          >
            {inviteLink ? (
              <>
                <p>
                  This link can be accepted once. Share it privately with the
                  intended person. It expires in seven days.
                </p>
                <label>
                  Invitation link
                  <textarea readOnly rows={3} value={inviteLink} />
                </label>
                <CopyButton
                  value={inviteLink}
                  label="Copy invitation"
                  disabled={busy}
                />
                <button
                  className="secondary-button"
                  onClick={() => setInviteLink("")}
                >
                  Create another invitation
                </button>
              </>
            ) : (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  const signer =
                    new FormData(e.currentTarget).get("signer") === "on";
                  void run(async () => {
                    const result = await api<{ token: string }>(
                      `/clans/${selected}/invitations`,
                      { is_signer: signer },
                    );
                    setInviteLink(`${location.origin}/join#${result.token}`);
                    await refresh();
                  });
                }}
              >
                <p className="lead">
                  People create their own account and accept your invitation.
                  They are never added automatically.
                </p>
                <label className="check-field">
                  <input
                    name="signer"
                    type="checkbox"
                    disabled={clan.signer_count >= clan.target_signers}
                  />
                  <span>
                    Offer a signatory role. The recipient must explicitly
                    accept. {clan.target_signers - clan.signer_count} places
                    remain.
                  </span>
                </label>
                <button className="primary-button" disabled={busy}>
                  <Busy busy={busy}>Create private invitation</Busy>
                  <Link />
                </button>
              </form>
            )}
          </Sheet>
        )}
        {modal === "request" && clan && (
          <Sheet title="Receive a grant" onClose={close} busy={busy}>
            <GrantRequest
              clanId={clan.id}
              requestKey={requestKey}
              busy={busy}
              run={run}
              onSent={async () => {
                setModal(null);
                await refresh();
                setNotice("Your request is ready for your clan to vote on.");
              }}
            />
          </Sheet>
        )}
        {modal === "vote" && clan && (
          <Sheet title="Vote & approve" onClose={close} busy={busy}>
            <p className="lead">
              Members vote on grant requests. Signatories approve the payments.
            </p>
            {clan.grants.filter(needsGrantAction).length ? (
              clan.grants.filter(needsGrantAction).map((item) => (
                <GrantCard
                  key={item.id}
                  grant={item}
                  busy={busy}
                  open={() => {
                    setModal(null);
                    setGrant(item);
                  }}
                />
              ))
            ) : (
              <div className="home-empty">
                <CheckCircle size={32} />
                <h3>You are up to date</h3>
                <p>No requests need your vote or approval.</p>
              </div>
            )}
          </Sheet>
        )}
        {modal === "repay" && clan && (
          <Sheet title="Repay your grant" onClose={close} busy={busy}>
            <p className="lead">
              Pay a little at a time or repay the full amount.
            </p>
            {clan.grants.filter(
              (item) =>
                item.beneficiary_id === session?.user?.id &&
                BigInt(item.outstanding_msat) > 0n,
            ).length ? (
              clan.grants
                .filter(
                  (item) =>
                    item.beneficiary_id === session?.user?.id &&
                    BigInt(item.outstanding_msat) > 0n,
                )
                .map((item) => (
                  <button
                    className="clan-option"
                    key={item.id}
                    disabled={busy || !canReceive}
                    onClick={() => {
                      setModal(null);
                      setDeposit({ grantId: item.id });
                    }}
                  >
                    <span>
                      <strong>
                        {owedLabel(item)} left to repay
                      </strong>
                      <small>{item.purpose}</small>
                    </span>
                    <ArrowRight />
                  </button>
                ))
            ) : (
              <div className="home-empty">
                <CheckCircle size={32} />
                <h3>Nothing to repay</h3>
                <p>
                  Your repayments will appear here after a grant is paid to you.
                </p>
              </div>
            )}
            {!canReceive && (
              <p className="field-help">
                Payments are temporarily unavailable. Please try again later.
              </p>
            )}
          </Sheet>
        )}
        {modal === "switch" && (
          <Sheet title="Your clans." onClose={close} busy={busy}>
            {session?.clans?.map((c) => (
              <button
                className="clan-option"
                key={c.id}
                onClick={() => chooseClan(c.id)}
              >
                <UsersThree size={25} />
                <span>
                  <strong>{c.name}</strong>
                  <small>
                    {c.member_count} members · {c.signer_threshold} of{" "}
                    {c.target_signers} signatories
                  </small>
                </span>
                {c.id === selected && <Check />}
              </button>
            ))}
            <button
              className="secondary-button"
              onClick={() => setModal("create")}
            >
              <Plus />
              Create a clan
            </button>
          </Sheet>
        )}
        {deposit && clan && (
          <DepositSheet
            key={`${clan.id}:${deposit.existing?.id || deposit.grantId || "new"}`}
            clanId={clan.id}
            clanName={clan.name}
            grantId={deposit.grantId}
            grant={clan.grants.find((g) => g.id === deposit.grantId)}
            existing={deposit.existing}
            max={session?.capabilities.max_invoice_sats || 100000}
            busy={busy}
            run={run}
            onClose={close}
            onRefresh={refresh}
          />
        )}
        {activityItem && clan && (
          <ActivityDetailSheet
            key={activityItem.id}
            clanId={clan.id}
            item={activityItem}
            labels={eventLabels}
            network={clanWallet.view?.network}
            canOpenGrant={(id) => clan.grants.some((item) => item.id === id)}
            canOpenPayment={!!clanWallet.view?.enabled}
            onOpenGrant={(id) => {
              const found = clan.grants.find((item) => item.id === id);
              if (!found) return;
              setActivityItem(null);
              setGrant(found);
            }}
            onOpenPayment={(id, grantId) => {
              setActivityItem(null);
              setActivityPayment({ id, grantId });
            }}
            onClose={() => setActivityItem(null)}
          />
        )}
        {activityPayment && clan && clanWallet.view && (
          <ActivityPaymentSheet
            key={activityPayment.id}
            clanId={clan.id}
            payoutId={activityPayment.id}
            grantId={activityPayment.grantId}
            view={clanWallet.view}
            userId={session?.user?.id}
            beneficiaryOf={(id) =>
              clan.grants.find((item) => item.id === id)?.beneficiary_id
            }
            onCheckWallet={() => {
              setActivityPayment(null);
              setTab("clan");
            }}
            onRefresh={refresh}
            onClose={() => setActivityPayment(null)}
          />
        )}
        {grant && clan && !deposit && (
          <Sheet
            title="Grant request"
            eyebrow={
              walletActive && grant.status === "awaiting_funding"
                ? "Add your Bitcoin address"
                : statusLabels[grant.status] || grant.status
            }
            onClose={close}
            busy={busy}
          >
            <div className="requester-line">
              <Avatar name={grant.beneficiary_name} />
              <span>{grant.beneficiary_name}</span>
            </div>
            <h2 className="review-amount">{satsLabel(grant.amount_sats)}</h2>
            <p className="grant-purpose">{grant.purpose}</p>
            <div className="policy-banner">
              <UsersThree size={25} />
              <div>
                <strong>
                  {grant.votes.filter((v) => v.choice === "approve").length}{" "}
                  approvals · {grant.votes.length} votes cast
                </strong>
                <p>
                  At least {grant.required_votes} approvals and a majority of
                  eligible voters are needed.
                </p>
              </div>
            </div>
            {grant.can_vote ? (
              <div className="vote-actions">
                {(["approve", "reject", "abstain"] as const).map((choice) => (
                  <button
                    className={
                      choice === "approve"
                        ? "primary-button"
                        : "secondary-button"
                    }
                    key={choice}
                    disabled={busy}
                    onClick={() =>
                      run(async () => {
                        await api(
                          `/clans/${selected}/grants/${grant.id}/vote`,
                          {
                            choice,
                          },
                        );
                        setGrant(null);
                        await refresh();
                        setNotice("Your vote is recorded.");
                      })
                    }
                  >
                    {choice === "approve"
                      ? "Approve request"
                      : choice === "reject"
                        ? "Reject request"
                        : "Abstain"}
                  </button>
                ))}
              </div>
            ) : (
              <p className="fine-print">
                {grant.beneficiary_id === session?.user?.id
                  ? "Other members vote on your request."
                  : "You have voted, or voting has ended."}
              </p>
            )}
            {grant.status === "awaiting_acceptance" &&
              grant.beneficiary_id === session?.user?.id && (
                <>
                  <p>
                    Accept the recoverable grant of{" "}
                    {satsLabel(grant.amount_sats)}. The recovery obligation
                    starts only when an actual payout is confirmed.
                  </p>
                  <button
                    className="primary-button"
                    disabled={busy}
                    onClick={() =>
                      run(async () => {
                        await api(
                          `/clans/${selected}/grants/${grant.id}/accept`,
                          {},
                        );
                        setGrant(null);
                        await refresh();
                        setNotice(
                          "Terms accepted. This grant is awaiting funding.",
                        );
                      })
                    }
                  >
                    <Busy busy={busy}>Accept grant terms</Busy>
                  </button>
                </>
              )}
            {grant.beneficiary_id === session?.user?.id &&
              [
                "voting",
                "awaiting_acceptance",
                "awaiting_funding",
                "awaiting_signatures",
              ].includes(grant.status) && (
                <button
                  className="secondary-button"
                  disabled={busy}
                  onClick={() =>
                    run(async () => {
                      await api(
                        `/clans/${selected}/grants/${grant.id}/cancel`,
                        {},
                      );
                      setGrant(null);
                      await refresh();
                      setNotice("Your request was withdrawn.");
                    })
                  }
                >
                  Withdraw my request
                </button>
              )}
            <GrantMoney
              key={grant.id}
              clanId={clan.id}
              grant={grant}
              isBeneficiary={grant.beneficiary_id === session?.user?.id}
              payoutsEnabled={!!session?.capabilities.payouts}
              receivingEnabled={!!session?.capabilities.receiving}
              busy={busy}
              run={run}
              onRefresh={refresh}
              onRepay={() => setDeposit({ grantId: grant.id })}
              onCheckWallet={() => {
                setGrant(null);
                setTab("clan");
              }}
            />
          </Sheet>
        )}
      </div>
    </FeedbackContext.Provider>
  );
}

function Step({ n, label }: { n: number; label: string }) {
  return (
    <div className="step-indicator">
      <div aria-label={`Step ${n} of 4`}>
        {[1, 2, 3, 4].map((i) => (
          <span className={i <= n ? "done" : ""} key={i} />
        ))}
      </div>
      <span>
        Step {n} of 4 · {label}
      </span>
    </div>
  );
}
function Nav({
  label,
  active,
  action,
  icon,
}: {
  label: string;
  active: boolean;
  action: () => void;
  icon: ReactNode;
}) {
  return (
    <button
      className={`nav-item ${active ? "active" : ""}`}
      onClick={action}
      aria-current={active ? "page" : undefined}
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}
function GrantHistory({
  grants,
  busy,
  open,
}: {
  grants: Grant[];
  busy: boolean;
  open: (grant: Grant) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [count, setCount] = useState(10);
  if (!grants.length) return null;
  return (
    <details
      className="activity-pending"
      onToggle={(event) => setExpanded(event.currentTarget.open)}
    >
      <summary>Recent grant requests</summary>
      {expanded && (
        <>
          {grants.slice(0, count).map((grant) => (
            <GrantCard
              key={grant.id}
              grant={grant}
              busy={busy}
              open={() => open(grant)}
            />
          ))}
          {count < grants.length && (
            <button
              className="secondary-button"
              onClick={() => setCount((value) => value + 10)}
            >
              Show more requests
            </button>
          )}
        </>
      )}
    </details>
  );
}

function GrantCard({
  grant,
  open,
  busy,
}: {
  grant: Grant;
  open: () => void;
  busy: boolean;
}) {
  return (
    <section className="grant-card">
      <div className="card-topline">
        <span>Grant request</span>
        <span className="decision-pill">
          {statusLabels[grant.status] || grant.status}
        </span>
      </div>
      <h2>{satsLabel(grant.amount_sats)}</h2>
      <p>
        {grant.beneficiary_name} · {grant.purpose}
      </p>
      <button className="primary-button" onClick={open} disabled={busy}>
        Review request
        <ArrowRight size={18} />
      </button>
    </section>
  );
}
function AccountInfo({
  view = "all",
  session,
  security,
  busy,
  logout,
  secureAction,
}: {
  view?: "all" | "details" | "security" | "limits";
  session: Session;
  security: {
    recovery_codes_remaining: number;
    passkeys: { id: string; label: string; backed_up: boolean }[];
  } | null;
  busy: boolean;
  logout: () => void;
  secureAction: (
    action: "add_passkey" | "recovery_codes" | "username",
    username?: string,
  ) => void;
}) {
  const [editingName, setEditingName] = useState(false);
  return (
    <section className="account-info">
      {(view === "all" || view === "details") && (
        <>
          <Avatar name={session.user!.display_name} />
          <h2>{session.user!.display_name}</h2>
          <p className="eyebrow">Your username</p>
          <p className="account-handle">{session.user!.handle}</p>
          <button
            className="text-button"
            onClick={() => setEditingName(!editingName)}
          >
            {editingName ? "Cancel" : "Change username"}
          </button>
          {editingName && (
            <form
              className="username-form"
              onSubmit={(event) => {
                event.preventDefault();
                const name = String(
                  new FormData(event.currentTarget).get("username") || "",
                );
                secureAction("username", name);
              }}
            >
              <label>
                New username
                <input
                  name="username"
                  required
                  minLength={3}
                  maxLength={24}
                  pattern="[a-z][a-z0-9_]{2,23}"
                  autoComplete="username"
                  autoCapitalize="none"
                  spellCheck={false}
                  defaultValue={
                    session.user!.handle.startsWith("clan-")
                      ? ""
                      : session.user!.handle
                  }
                />
              </label>
              <button className="secondary-button" disabled={busy}>
                Save with my passkey
              </button>
            </form>
          )}
        </>
      )}
      {(view === "all" || view === "limits") &&
        session.capabilities.payout_budget_currency === "KES" && (
          <div className="policy-banner">
            <ShieldCheck size={27} />
            <div>
              <strong>Payment limits</strong>
              <p>
                Up to KES{" "}
                {session.capabilities.max_payout_kes?.toLocaleString()} per
                payment, including its fee. Each clan can send up to KES{" "}
                {session.capabilities.payout_clan_24h_kes?.toLocaleString()} in
                24 hours.
              </p>
              <p>
                All clans share a KES{" "}
                {session.capabilities.payout_global_24h_kes?.toLocaleString()}{" "}
                daily allowance. The Bitcoin rate is checked before sending.
              </p>
            </div>
          </div>
        )}
      {(view === "all" || view === "security") && (
        <>
          <div className="policy-banner">
            <Fingerprint size={27} />
            <div>
              <strong>Protected by passkeys</strong>
              <p>
                {security
                  ? `${security.passkeys.length} active passkey · ${security.recovery_codes_remaining ? "Recovery backup ready" : "No recovery backup left"}`
                  : "Your passkey stays with your device or password manager."}
              </p>
            </div>
          </div>
          <p className="fine-print">
            Keep your recovery words private. Use “Recover your account” on the
            welcome screen if you lose your passkey. You keep the same clan,
            grants and repayments. A recovered signatory needs a payment safety
            check before approving payments.
          </p>
          <div className="settings-actions">
            <button
              className="secondary-button"
              disabled={busy}
              onClick={() => secureAction("add_passkey")}
            >
              <Fingerprint size={20} />
              Add another passkey
            </button>
            <button
              className="secondary-button"
              disabled={busy}
              onClick={() => secureAction("recovery_codes")}
            >
              <ShieldCheck size={20} />
              Get new recovery words
            </button>
          </div>
        </>
      )}
      {view === "all" && (
        <button className="secondary-button" disabled={busy} onClick={logout}>
          <SignOut size={20} />
          Sign out
        </button>
      )}
    </section>
  );
}
function InviteAcceptance({
  info,
  busy,
  onAccept,
}: {
  info: {
    name: string;
    is_signer: boolean;
    invited_by: string;
    custody_notice: string;
  };
  busy: boolean;
  onAccept: (signer: boolean) => void;
}) {
  const [accepted, setAccepted] = useState(false);
  const [signer, setSigner] = useState(false);
  return (
    <div className="invite-preview">
      <span className="eyebrow">Invited by {info.invited_by}</span>
      <h2>{info.name}</h2>
      <p>
        You are invited as{" "}
        {info.is_signer ? "a member and signatory" : "a member"}. Your name will
        be visible to this clan.
      </p>
      <p className="custody-copy">{info.custody_notice}</p>
      <label className="check-field">
        <input
          type="checkbox"
          checked={accepted}
          onChange={(e) => setAccepted(e.target.checked)}
        />
        <span>
          I choose to join this clan and acknowledge the custody terms.
        </span>
      </label>
      {info.is_signer && (
        <label className="check-field">
          <input
            type="checkbox"
            checked={signer}
            onChange={(e) => setSigner(e.target.checked)}
          />
          <span>
            I accept the signatory responsibility and will independently review
            payment requests.
          </span>
        </label>
      )}
      <button
        className="primary-button"
        disabled={busy || !accepted || (info.is_signer && !signer)}
        onClick={() => onAccept(signer)}
      >
        <Busy busy={busy}>Accept invitation</Busy>
        <Check />
      </button>
    </div>
  );
}
function CreateClan({
  busy,
  custody,
  onSubmit,
}: {
  busy: boolean;
  custody: string;
  onSubmit: (data: unknown) => void;
}) {
  const [step, setStep] = useState(1);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [communityCode, setCommunityCode] = useState("");
  const [signers, setSigners] = useState(3);
  return step === 1 ? (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        setStep(2);
      }}
    >
      <p className="lead">Give your circle a name and a shared purpose.</p>
      <label>
        Clan name
        <input
          required
          minLength={2}
          maxLength={100}
          value={name}
          onChange={(e) => setName(e.target.value)}
          autoFocus
        />
      </label>
      <label>
        What brings you together?
        <textarea
          maxLength={500}
          rows={3}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </label>
      <label>
        Community code (optional)
        <input
          maxLength={20}
          autoComplete="off"
          autoCapitalize="characters"
          spellCheck={false}
          placeholder="ABCD-EFGH"
          value={communityCode}
          onChange={(e) => setCommunityCode(e.target.value)}
        />
      </label>
      <p className="fine-print">
        If your community gave you a code, type it here, and its team approves
        your clan wallet payments. Leave it empty to be overseen by Afribit.
      </p>
      <button className="primary-button">
        Choose who approves
        <ArrowRight />
      </button>
    </form>
  ) : (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        const data = new FormData(e.currentTarget);
        onSubmit({
          name,
          description,
          target_signers: signers,
          member_vote_quorum: Number(data.get("quorum")),
          be_signer: data.get("signer") === "on",
          accepted_custody: data.get("custody") === "on",
          ...(communityCode.trim() ? { community_code: communityCode.trim() } : {}),
        });
      }}
    >
      <button type="button" className="back-button" onClick={() => setStep(1)}>
        <ArrowLeft />
        Back to clan details
      </button>
      <p className="eyebrow">Create your clan · 2 of 2</p>
      <h3>Agree on the rules.</h3>
      <label>
        Number of signatories
        <select
          value={signers}
          onChange={(e) => setSigners(Number(e.target.value))}
        >
          <option value={3}>3 signatories · 2 approvals</option>
          <option value={5}>5 signatories · 3 approvals</option>
          <option value={7}>7 signatories · 4 approvals</option>
        </select>
      </label>
      <label>
        Minimum approving member votes
        <input
          name="quorum"
          type="number"
          required
          min={1}
          max={100}
          defaultValue={2}
        />
      </label>
      <p className="fine-print">
        A majority of eligible voters is also required. The beneficiary cannot
        vote or sign for their own grant. These rules are fixed when the clan is
        created.
      </p>
      <label className="check-field">
        <input name="signer" type="checkbox" />
        <span>I also choose to be one of the signatories.</span>
      </label>
      <p className="custody-copy">{custody}</p>
      <label className="check-field">
        <input name="custody" type="checkbox" required />
        <span>
          I acknowledge these custody terms and will share them with members.
        </span>
      </label>
      <button className="primary-button" disabled={busy}>
        <Busy busy={busy}>Create {name}</Busy>
        <Plus />
      </button>
    </form>
  );
}
