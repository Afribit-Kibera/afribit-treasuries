import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  House,
  UsersThree,
  ListBullets,
  User,
  Plus,
  Bell,
  Sun,
  Moon,
  ArrowUpRight,
  Stack,
  FileText,
  CaretDown,
  CaretRight,
  Check,
  ShieldCheck,
  ArrowDownLeft,
  HandHeart,
  Lightning,
  CheckCircle,
  ArrowClockwise,
  Eye,
  EyeSlash,
} from "@phosphor-icons/react";
import { ApiError, command, getDashboard, getSession, request } from "./api";
import type { Clan, Grant, Member, Run, Session, SimEvent } from "./types";
import { Avatar, Busy, Sheet, demoKes, kes, satsLabel, toSats } from "./ui";

type Tab = "home" | "clan" | "activity" | "profile";
type Modal =
  | "actions"
  | "request"
  | "contribute"
  | "repay"
  | "review"
  | "create"
  | "clans"
  | "notifications"
  | "recovery"
  | null;
type ActivityFilter = "all" | "grants" | "contributions" | "recovery";
const labels: Record<string, string> = {
  contribute: "Treasury contribution",
  request_grant: "Grant requested",
  vote: "Member vote recorded",
  accept_terms: "Recovery terms accepted",
  freeze_intent: "Grant prepared for approval",
  approve_intent: "Signatory approval",
  execute: "Demo grant issued",
  cancel_intent: "Approval request canceled",
  repay: "Recovery contribution",
  propose_amendment: "Recovery adjustment proposed",
  vote_amendment: "Adjustment vote recorded",
};
const statusLabels: Record<string, string> = {
  voting: "Pending decision",
  accepted: "Awaiting acceptance",
  terms_accepted: "Ready for signatories",
  awaiting_signers: "Awaiting signatories",
  authorized: "Ready to issue",
  settled_simulated: "In recovery",
  rejected: "Not approved",
};

export default function App() {
  const [theme, setTheme] = useState(
    document.documentElement.dataset.theme || "dark",
  );
  const [tab, setTab] = useState<Tab>("home");
  const [session, setSession] = useState<Session | null>(null);
  const [clan, setClan] = useState<Clan | null>(null);
  const [members, setMembers] = useState<Member[]>([]);
  const [run, setRun] = useState<Run | null>(null);
  const [persona, setPersona] = useState("chair");
  const [modal, setModal] = useState<Modal>(null);
  const [selectedId, setSelectedId] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const [showActivity, setShowActivity] = useState(false);
  const [showBalance, setShowBalance] = useState(true);
  const [filter, setFilter] = useState<ActivityFilter>("all");
  const [amount, setAmount] = useState("");
  const [purpose, setPurpose] = useState("");
  const [newName, setNewName] = useState("");
  const [preset, setPreset] = useState(3);
  const [repaymentMethod, setRepaymentMethod] = useState("lightning");
  const [clans, setClans] = useState<Clan[]>([]);
  const [offline, setOffline] = useState(!navigator.onLine);
  const pending = useRef<{ signature: string; key: string } | null>(null);
  const recoveryReference = useRef("");
  const activeOperation = useRef(false);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document
      .querySelector('meta[name="theme-color"]')
      ?.setAttribute("content", theme === "dark" ? "#0c0d0c" : "#f6f5ee");
    try {
      localStorage.setItem("clans-theme", theme);
    } catch {
      /* Storage can be unavailable. */
    }
  }, [theme]);
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(""), 4500);
    return () => clearTimeout(timer);
  }, [toast]);
  useEffect(() => {
    const online = () => setOffline(false),
      offline = () => setOffline(true);
    window.addEventListener("online", online);
    window.addEventListener("offline", offline);
    return () => {
      window.removeEventListener("online", online);
      window.removeEventListener("offline", offline);
    };
  }, []);
  useEffect(() => {
    let current = true;
    getSession()
      .then(async (info) => {
        // A separate simulation run lets browser QA leave the owner's preview untouched.
        const demoRun = new URLSearchParams(window.location.search).get(
          "demoRun",
        );
        const selectedSession = { ...info, run_id: demoRun || info.run_id };
        const data = await getDashboard(
          info.clan_id,
          selectedSession.run_id,
          "chair",
        );
        if (current) {
          setSession(selectedSession);
          setClan(data.clan);
          setMembers(data.members);
          setRun(data.run);
        }
      })
      .catch(() => {
        if (current)
          setError(
            "Your demo is not connected. Start the local backend, then reconnect below.",
          );
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => {
      current = false;
    };
  }, []);

  const grants = Object.values(run?.state.grants || {});
  const pendingGrants = grants.filter(
    (grant) => !["settled_simulated", "rejected"].includes(grant.status),
  );
  const recovering = grants.filter(
    (grant) =>
      grant.status === "settled_simulated" && grant.outstanding_minor > 0,
  );
  const selected = grants.find((grant) => grant.id === selectedId);
  const featured = pendingGrants.at(-1);
  const currentUser = session?.personas.find((user) => user.key === persona);
  const currentMember = members.find(
    (member) => member.user.id === currentUser?.id,
  );
  const recoveryKes = recovering.reduce(
    (sum, grant) =>
      sum +
      (grant.obligation_currency === "KES"
        ? grant.outstanding_minor / 100
        : demoKes(grant.outstanding_minor)),
    0,
  );
  const nameOf = (id: string) =>
    session?.personas.find((user) => user.id === id)?.display_name ||
    members.find((member) => member.user.id === id)?.user.display_name ||
    "Clan member";
  const isSigner = !!currentMember?.is_signer;
  const available = demoKes(run?.state.available_sats || 0);

  function open(next: Modal, grant?: Grant) {
    setError("");
    setAmount("");
    setPurpose("");
    setRepaymentMethod("lightning");
    if (next === "repay")
      recoveryReference.current = `sim:${crypto.randomUUID()}`;
    if (grant) setSelectedId(grant.id);
    if (next === "repay" && !grant)
      setSelectedId(
        recovering.find((item) => item.beneficiary_id === currentUser?.id)
          ?.id ||
          recovering[0]?.id ||
          "",
      );
    setModal(next);
  }

  async function refresh() {
    if (!clan || !run) return;
    const data = await getDashboard(clan.id, run.id, persona);
    setClan(data.clan);
    setMembers(data.members);
    setRun(data.run);
  }

  async function act(
    body: Record<string, unknown>,
    message: string,
    close = false,
  ) {
    if (!clan || !run || activeOperation.current || offline) return;
    activeOperation.current = true;
    setBusy(true);
    setError("");
    const signature = JSON.stringify({
      persona,
      clan: clan.id,
      run: run.id,
      body,
    });
    if (pending.current?.signature !== signature)
      pending.current = { signature, key: crypto.randomUUID() };
    try {
      const result = await command(
        clan.id,
        run.id,
        persona,
        body,
        pending.current.key,
      );
      setRun(result);
      pending.current = null;
      setToast(message);
      if (close) setModal(null);
    } catch (problem) {
      if (problem instanceof ApiError && problem.status < 500)
        pending.current = null;
      setError(
        problem instanceof Error
          ? problem.message
          : "That action could not be completed.",
      );
      // An uncertain network result keeps its key; an exact retry cannot double credit.
      await refresh().catch(() => {});
    } finally {
      setBusy(false);
      activeOperation.current = false;
    }
  }

  async function switchPersona(next: string) {
    if (!clan || !run || activeOperation.current) return;
    setBusy(true);
    setError("");
    try {
      const data = await getDashboard(clan.id, run.id, next);
      setClan(data.clan);
      setMembers(data.members);
      setRun(data.run);
      setPersona(next);
      setToast(
        `Now viewing as ${session?.personas.find((user) => user.key === next)?.display_name.split(" ")[0]}`,
      );
    } catch (problem) {
      setError(
        problem instanceof Error ? problem.message : "Could not switch member.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function submitMoney(event: FormEvent) {
    event.preventDefault();
    try {
      const amount_sats = toSats(amount);
      if (modal === "contribute")
        await act(
          { action: "contribute", amount_sats },
          "Your demo contribution is in. Together, we grow.",
          true,
        );
      if (modal === "request")
        await act(
          {
            action: "request_grant",
            amount_sats,
            purpose,
            obligation_currency: "KES",
            kes_minor_per_1000_sats: 2500,
          },
          "Your request is ready for the clan to review.",
          true,
        );
      if (modal === "repay" && selected)
        await act(
          {
            action: "repay",
            grant_id: selected.id,
            amount_sats,
            method: repaymentMethod,
            settlement_reference: recoveryReference.current,
            ...(repaymentMethod === "otc"
              ? {
                  remitter_user_id: session?.personas.find(
                    (user) => user.key === "otc_merchant",
                  )?.id,
                }
              : {}),
          },
          "Recovery recorded. That capital can support someone else.",
          true,
        );
    } catch (problem) {
      setError(
        problem instanceof Error ? problem.message : "Check the amount.",
      );
    }
  }

  async function createClan(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const created = await request<Clan>("/api/v1/clans", persona, {
        name: newName,
        policy: {
          currency: "KES",
          member_vote_quorum: 3,
          signer_threshold: (preset + 1) / 2,
          beneficiary_can_approve: false,
        },
      });
      const createdRun = await request<Run>(
        `/api/v1/clans/${created.id}/simulations`,
        persona,
        { name: `${created.name} treasury` },
      );
      const roster = await request<Member[]>(
        `/api/v1/clans/${created.id}/members`,
        persona,
      );
      setClan(created);
      setRun(createdRun);
      setMembers(roster);
      setModal(null);
      setTab("clan");
      setToast("Your clan is created. No deposit was needed.");
    } catch (problem) {
      setError(
        problem instanceof Error
          ? problem.message
          : "Check your clans before retrying creation.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function openClans() {
    setError("");
    setModal("clans");
    try {
      setClans(await request<Clan[]>("/api/v1/clans", persona));
    } catch (problem) {
      setError(
        problem instanceof Error ? problem.message : "Could not load clans.",
      );
    }
  }

  async function selectClan(next: Clan) {
    if (next.id === clan?.id) {
      setModal(null);
      return;
    }
    setBusy(true);
    setError("");
    try {
      let runId = session?.clan_id === next.id ? session.run_id : "";
      const saved = sessionStorage.getItem(`clans-run:${next.id}`);
      if (saved) runId = saved;
      if (!runId) {
        const started = await request<Run>(
          `/api/v1/clans/${next.id}/simulations`,
          persona,
          { name: `${next.name} treasury` },
        );
        runId = started.id;
        sessionStorage.setItem(`clans-run:${next.id}`, runId);
      }
      const data = await getDashboard(next.id, runId, persona);
      setClan(data.clan);
      setMembers(data.members);
      setRun(data.run);
      setModal(null);
      setTab("home");
    } catch (problem) {
      setError(
        problem instanceof Error ? problem.message : "Could not open clan.",
      );
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (clan && run) {
      try {
        sessionStorage.setItem(`clans-run:${clan.id}`, run.id);
      } catch {}
    }
  }, [clan?.id, run?.id]);

  function activityRows(limit?: number) {
    let events = [...(run?.state.events || [])]
      .reverse()
      .filter(
        (event) =>
          filter === "all" ||
          (filter === "contributions"
            ? event.action === "contribute"
            : filter === "recovery"
              ? ["repay", "propose_amendment", "vote_amendment"].includes(
                  event.action,
                )
              : ![
                  "contribute",
                  "repay",
                  "propose_amendment",
                  "vote_amendment",
                ].includes(event.action)),
      );
    if (limit) events = events.slice(0, limit);
    return events.length ? (
      <div className="activity-list">
        {events.map((event, index) => (
          <ActivityRow
            key={`${event.actor_id}-${event.action}-${index}`}
            event={event}
            name={nameOf(event.actor_id)}
          />
        ))}
      </div>
    ) : (
      <div className="empty-inline">
        <Stack size={28} />
        <p>Every step forward starts somewhere.</p>
        <span>Your clan’s activity will appear here.</span>
      </div>
    );
  }

  const disabled = busy || offline;
  return (
    <div className="app">
      <div className="background-art" aria-hidden="true" />
      <div className="app-shell">
        <header className="app-header">
          <button
            className="brand"
            aria-label="AfriBit Clans home"
            onClick={() => setTab("home")}
          >
            <img src="/assets/afribit-mark.png" alt="" />
            <span className="brand-divider" />
            <span className="wordmark">
              Afri<span>B</span>it <em>Clans</em>
            </span>
          </button>
          <div className="header-actions">
            <button
              className="icon-button theme-toggle"
              aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            >
              {theme === "dark" ? <Sun size={21} /> : <Moon size={21} />}
            </button>
            <button
              className="icon-button notification-button"
              aria-label="Notifications"
              onClick={() => open("notifications")}
            >
              <Bell size={23} />
              <span className="notification-dot" />
            </button>
          </div>
        </header>

        {offline && (
          <div className="connection-banner" role="status">
            You’re offline. Your treasury is read-only until you reconnect.
          </div>
        )}
        {loading ? (
          <main className="loading-state">
            <Stack className="pulse" size={38} />
            <h1>Gathering your circle.</h1>
            <p>A shared future starts with your people.</p>
          </main>
        ) : !clan || !run ? (
          <main className="loading-state">
            <HandHeart size={42} />
            <h1>Your circle awaits.</h1>
            <p>{error}</p>
            <button
              className="primary-button"
              onClick={() => window.location.reload()}
            >
              <ArrowClockwise size={18} /> Reconnect demo
            </button>
          </main>
        ) : (
          <>
            <main id="main-content" className={`main-content page-${tab}`}>
              <div className="page-heading">
                <div>
                  <div className="clan-title-row">
                    <button className="clan-title" onClick={openClans}>
                      <h1>{clan.name}</h1>
                      <CaretDown size={17} />
                    </button>
                    <span
                      className={`status-pill ${clan.governance_ready ? "" : "setup-pill"}`}
                    >
                      <span />
                      {clan.governance_ready ? "Active" : "Setting up"}
                    </span>
                  </div>
                  <p>
                    {tab === "home"
                      ? "Collective treasury for recoverable grants."
                      : tab === "clan"
                        ? "Your people. A shared purpose."
                        : tab === "activity"
                          ? "Every contribution. Every step forward."
                          : "Your place in the circle."}
                  </p>
                </div>
                <span className="demo-label">
                  <span />
                  Demo treasury
                </span>
              </div>

              {tab === "home" && (
                <div className="home-layout">
                  <section
                    className="treasury-column"
                    aria-label="Treasury overview"
                  >
                    <div className="balance-panel">
                      <div className="balance-heading">
                        <span className="eyebrow">Available capital</span>
                        <button
                          className="icon-button eye-button"
                          aria-label={
                            showBalance ? "Hide balance" : "Show balance"
                          }
                          onClick={() => setShowBalance(!showBalance)}
                        >
                          {showBalance ? (
                            <Eye size={18} />
                          ) : (
                            <EyeSlash size={18} />
                          )}
                        </button>
                      </div>
                      <div
                        className={`balance-number ${!showBalance ? "balance-hidden" : ""}`}
                      >
                        {showBalance ? kes(available) : "••••••"}
                      </div>
                      <span className="balance-rule" />
                      <p className="balance-detail">
                        <Lightning size={13} />
                        {showBalance
                          ? satsLabel(run.state.available_sats)
                          : "Balance hidden"}
                        <span>Fixed demo valuation</span>
                      </p>
                    </div>
                    <button
                      className="recovery-strip"
                      onClick={() => open("recovery")}
                    >
                      <Stack size={23} weight="light" />
                      <span className="strip-divider" />
                      <span>In recovery</span>
                      <i />
                      <strong>
                        {showBalance ? kes(recoveryKes) : "••••••"}
                      </strong>
                      <CaretRight size={15} />
                    </button>
                    {featured ? (
                      <section className="grant-card">
                        <div className="card-topline">
                          <span>
                            <FileText size={23} weight="light" />
                            Grant request
                          </span>
                          <span className="decision-pill">
                            {statusLabels[featured.status]}
                          </span>
                        </div>
                        <h2>{kes(demoKes(featured.amount_sats))}</h2>
                        <div className="requester-line">
                          <Avatar
                            name={nameOf(featured.beneficiary_id)}
                            small
                          />
                          <span>
                            {nameOf(featured.beneficiary_id).split(" ")[0]}’s
                            next step
                          </span>
                          <span className="votes-summary">
                            {
                              Object.values(featured.votes).filter(
                                (vote) => vote === "approve",
                              ).length
                            }
                            /{clan.policy.member_vote_quorum} votes
                          </span>
                        </div>
                        <button
                          className="primary-button"
                          onClick={() => open("review", featured)}
                        >
                          Review request
                          <ArrowUpRight size={18} />
                        </button>
                      </section>
                    ) : (
                      <section className="grant-card all-clear">
                        <CheckCircle size={28} weight="light" />
                        <h2>A little room to grow.</h2>
                        <p>Your clan has no pending requests.</p>
                        <button
                          className="primary-button"
                          onClick={() => open("request")}
                        >
                          Request a grant
                          <Plus size={18} />
                        </button>
                      </section>
                    )}
                    <button
                      className="activity-reveal"
                      aria-expanded={showActivity}
                      onClick={() => setShowActivity(!showActivity)}
                    >
                      <CaretDown
                        size={17}
                        className={showActivity ? "rotated" : ""}
                      />
                      <span />
                      <span>
                        {showActivity
                          ? "Hide recent activity"
                          : "Reveal recent activity"}
                      </span>
                    </button>
                    {showActivity && (
                      <section className="recent-activity">
                        <div className="section-header">
                          <h2>In your circle</h2>
                          <button
                            className="text-button"
                            onClick={() => {
                              setTab("activity");
                              setFilter("all");
                            }}
                          >
                            View all
                            <ArrowUpRight size={15} />
                          </button>
                        </div>
                        {activityRows(4)}
                      </section>
                    )}
                    <p className="mobile-motto">
                      A little from each. <em>More for everyone.</em>
                    </p>
                  </section>
                  <aside className="circle-panel">
                    <div className="section-header">
                      <span className="eyebrow">Stronger, together</span>
                      <ShieldCheck size={20} />
                    </div>
                    <div className="avatar-stack">
                      {members.slice(0, 5).map((member) => (
                        <Avatar
                          key={member.user.id}
                          name={member.user.display_name}
                        />
                      ))}
                    </div>
                    <h2>
                      {members.length} people.
                      <br />
                      <em>One shared future.</em>
                    </h2>
                    <p>
                      Capital that moves through your community, then comes back
                      to help the next person.
                    </p>
                    <button
                      className="text-button"
                      onClick={() => setTab("clan")}
                    >
                      Meet your clan
                      <ArrowUpRight size={17} />
                    </button>
                    <div className="circle-divider" />
                    <div className="mini-metric">
                      <ShieldCheck size={23} weight="light" />
                      <div>
                        <strong>
                          {clan.policy.signer_threshold} of {clan.signer_count}{" "}
                          signatories
                        </strong>
                        <span>Every grant. A collective decision.</span>
                      </div>
                    </div>
                    <div className="mini-metric">
                      <HandHeart size={23} weight="light" />
                      <div>
                        <strong>
                          {kes(demoKes(run.state.recovered_sats))} recovered
                        </strong>
                        <span>Ready to make a difference again.</span>
                      </div>
                    </div>
                    <span className="circle-footer">
                      Built on Bitcoin. Rooted in community.
                    </span>
                  </aside>
                </div>
              )}

              {tab === "clan" && (
                <section className="content-page">
                  <div className="section-header">
                    <h2>The people behind the progress.</h2>
                    <span className="count-label">
                      {members.length}{" "}
                      {members.length === 1 ? "member" : "members"}
                    </span>
                  </div>
                  <div className="policy-card">
                    <ShieldCheck size={28} weight="light" />
                    <div>
                      <strong>
                        {clan.policy.signer_threshold} approvals required
                      </strong>
                      <p>
                        {clan.signer_count} assigned signatories ·{" "}
                        {clan.policy.member_vote_quorum} member votes per grant
                      </p>
                    </div>
                  </div>
                  {!clan.governance_ready && (
                    <div className="notice">
                      <strong>Your clan is created.</strong>
                      <p>
                        No funding was needed. Member invitations and signer
                        assignment are the next implementation step; payouts
                        stay unavailable until your roster meets the policy.
                      </p>
                    </div>
                  )}
                  <div className="member-list">
                    {members.map((member) => (
                      <div className="member-row" key={member.user.id}>
                        <Avatar name={member.user.display_name} />
                        <div>
                          <strong>
                            {member.user.display_name}
                            {member.user.id === currentUser?.id ? " (you)" : ""}
                          </strong>
                          <span>
                            {member.role === "organizer"
                              ? "Organizer"
                              : member.role === "chairperson"
                                ? "Chairperson"
                                : member.role === "treasurer"
                                  ? "Treasurer"
                                  : member.role === "secretary"
                                    ? "Secretary"
                                    : "Member"}
                          </span>
                        </div>
                        {member.is_signer && (
                          <span className="signer-label">
                            <ShieldCheck size={14} />
                            Signatory
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                  <button
                    className="secondary-button full-width"
                    onClick={() => open("create")}
                  >
                    <Plus size={18} /> Create another clan
                  </button>
                  <p className="section-footnote">
                    Members decide who receives a grant. Signatories separately
                    approve its exact payment details.
                  </p>
                </section>
              )}

              {tab === "activity" && (
                <section className="content-page">
                  <div className="section-header">
                    <h2>The story so far.</h2>
                    <span className="count-label">
                      {run.state.events.length} moments
                    </span>
                  </div>
                  <div className="filter-tabs" aria-label="Filter activity">
                    {(
                      [
                        "all",
                        "grants",
                        "contributions",
                        "recovery",
                      ] as ActivityFilter[]
                    ).map((value) => (
                      <button
                        key={value}
                        className={filter === value ? "selected" : ""}
                        aria-pressed={filter === value}
                        onClick={() => setFilter(value)}
                      >
                        {value === "all"
                          ? "All activity"
                          : value[0].toUpperCase() + value.slice(1)}
                      </button>
                    ))}
                  </div>
                  {activityRows()}
                </section>
              )}

              {tab === "profile" && (
                <section className="content-page">
                  <div className="profile-card">
                    <Avatar name={currentUser?.display_name || "Clan Member"} />
                    <h2>{currentUser?.display_name}</h2>
                    <p>
                      {currentMember?.role === "chairperson"
                        ? "Chairperson"
                        : currentMember?.role || "Member"}
                      {isSigner ? " · Signatory" : ""}
                    </p>
                    <span className="status-pill">
                      <span />
                      Part of something bigger
                    </span>
                  </div>
                  <div className="settings-list">
                    <button
                      onClick={() =>
                        setTheme(theme === "dark" ? "light" : "dark")
                      }
                    >
                      {theme === "dark" ? (
                        <Moon size={22} />
                      ) : (
                        <Sun size={22} />
                      )}
                      <span>
                        Appearance
                        <strong>
                          {theme === "dark"
                            ? "Midnight · Amber"
                            : "Daylight · Forest"}
                        </strong>
                      </span>
                      <span className="theme-swatch" />
                      <CaretRight size={16} />
                    </button>
                    <button onClick={openClans}>
                      <UsersThree size={22} />
                      <span>
                        Your clans<strong>Find your people</strong>
                      </span>
                      <CaretRight size={16} />
                    </button>
                    <button onClick={() => open("create")}>
                      <Plus size={22} />
                      <span>
                        Start a new clan<strong>No deposit required</strong>
                      </span>
                      <CaretRight size={16} />
                    </button>
                  </div>
                  <section className="demo-member-panel">
                    <span className="eyebrow">
                      Try the other side of the circle
                    </span>
                    <h3>Switch demo member</h3>
                    <p>
                      Review a request as a voter, accept as its recipient, or
                      approve as a signatory.
                    </p>
                    <label className="field-label" htmlFor="demo-member">
                      Viewing as
                    </label>
                    <select
                      id="demo-member"
                      value={persona}
                      disabled={disabled}
                      onChange={(event) => switchPersona(event.target.value)}
                    >
                      {session?.personas
                        .filter((user) =>
                          members.some((member) => member.user.id === user.id),
                        )
                        .map((user) => (
                          <option key={user.key} value={user.key}>
                            {user.display_name}
                          </option>
                        ))}
                    </select>
                  </section>
                </section>
              )}
            </main>
            <footer className="environment-note">
              <span />
              Interactive demo · No real payments
            </footer>
          </>
        )}

        <nav className="bottom-nav" aria-label="Main navigation">
          <button
            className={tab === "home" ? "active" : ""}
            aria-current={tab === "home" ? "page" : undefined}
            onClick={() => setTab("home")}
          >
            <House size={24} weight={tab === "home" ? "fill" : "light"} />
            <span>Home</span>
          </button>
          <button
            className={tab === "clan" ? "active" : ""}
            aria-current={tab === "clan" ? "page" : undefined}
            onClick={() => setTab("clan")}
          >
            <UsersThree size={25} weight="light" />
            <span>My Clan</span>
          </button>
          <button
            className="create-button"
            aria-label="Add a contribution, request, repayment or clan"
            disabled={!run}
            onClick={() => open("actions")}
          >
            <Plus size={31} weight="light" />
          </button>
          <button
            className={tab === "activity" ? "active" : ""}
            aria-current={tab === "activity" ? "page" : undefined}
            onClick={() => {
              setTab("activity");
              setFilter("all");
            }}
          >
            <ListBullets size={25} weight="light" />
            <span>Activity</span>
          </button>
          <button
            className={tab === "profile" ? "active" : ""}
            aria-current={tab === "profile" ? "page" : undefined}
            onClick={() => setTab("profile")}
          >
            <User size={24} weight="light" />
            <span>Profile</span>
          </button>
        </nav>

        {modal && (
          <Sheet
            title={
              modal === "actions"
                ? "Make a little progress."
                : modal === "request"
                  ? "Your next step."
                  : modal === "contribute"
                    ? "Add to your shared future."
                    : modal === "repay"
                      ? "Bring it back to the circle."
                      : modal === "review"
                        ? "A little support. A big step."
                        : modal === "create"
                          ? "Start something together."
                          : modal === "clans"
                            ? "Your circles."
                            : modal === "notifications"
                              ? "In the loop."
                              : "Capital coming full circle."
            }
            eyebrow={modal === "create" ? "A new clan" : clan?.name}
            onClose={() => {
              if (!busy) {
                setModal(null);
                setError("");
              }
            }}
          >
            {error && (
              <div className="error-message" role="alert">
                {error}
              </div>
            )}
            {offline && (
              <div className="notice">
                Reconnect to record changes. Your latest displayed balance may
                be out of date.
              </div>
            )}
            {modal === "actions" && (
              <div className="action-list">
                <button onClick={() => open("contribute")}>
                  <span className="action-icon">
                    <ArrowDownLeft size={23} />
                  </span>
                  <span>
                    <strong>Contribute</strong>
                    <small>Give your clan more room to grow</small>
                  </span>
                  <CaretRight size={18} />
                </button>
                <button onClick={() => open("request")}>
                  <span className="action-icon">
                    <FileText size={23} />
                  </span>
                  <span>
                    <strong>Request a grant</strong>
                    <small>Let your people back your next step</small>
                  </span>
                  <CaretRight size={18} />
                </button>
                <button
                  onClick={() => open("repay")}
                  disabled={!recovering.length}
                >
                  <span className="action-icon">
                    <HandHeart size={23} />
                  </span>
                  <span>
                    <strong>Make a recovery payment</strong>
                    <small>Keep the capital moving</small>
                  </span>
                  <CaretRight size={18} />
                </button>
                <button onClick={() => open("create")}>
                  <span className="action-icon">
                    <UsersThree size={23} />
                  </span>
                  <span>
                    <strong>Create a clan</strong>
                    <small>Bring a new circle together</small>
                  </span>
                  <CaretRight size={18} />
                </button>
              </div>
            )}

            {["request", "contribute", "repay"].includes(modal) && (
              <form onSubmit={submitMoney} className="money-form">
                <p className="form-intro">
                  {modal === "request"
                    ? "A recoverable grant, backed by the people who believe in you."
                    : modal === "contribute"
                      ? "Every contribution becomes an opportunity for someone in your clan."
                      : "Your recovery helps fund the next member’s opportunity."}
                </p>
                {modal === "repay" && (
                  <>
                    <label className="field-label" htmlFor="recovery-grant">
                      Grant to recover
                    </label>
                    <select
                      id="recovery-grant"
                      value={selectedId}
                      onChange={(event) => setSelectedId(event.target.value)}
                    >
                      {recovering.map((grant) => (
                        <option key={grant.id} value={grant.id}>
                          {nameOf(grant.beneficiary_id)} ·{" "}
                          {kes(
                            grant.obligation_currency === "KES"
                              ? grant.outstanding_minor / 100
                              : demoKes(grant.outstanding_minor),
                          )}{" "}
                          remaining
                        </option>
                      ))}
                    </select>
                    {selected &&
                      selected.beneficiary_id !== currentUser?.id && (
                        <div className="notice">
                          This grant belongs to{" "}
                          {nameOf(selected.beneficiary_id)}. Switch to that demo
                          member in Profile to record their recovery.
                        </div>
                      )}
                  </>
                )}
                <label className="field-label" htmlFor="money-amount">
                  Amount in Kenyan shillings
                </label>
                <div className="amount-input">
                  <span>KES</span>
                  <input
                    id="money-amount"
                    type="number"
                    inputMode="decimal"
                    min="0.025"
                    step="0.025"
                    placeholder="0"
                    value={amount}
                    onChange={(event) => setAmount(event.target.value)}
                    required
                  />
                </div>
                <div className="amount-conversion">
                  <Lightning size={13} />
                  {amount && Number(amount) > 0
                    ? `${satsLabel(Number(amount) * 40)} at the fixed demo rate`
                    : "Fixed demo rate · 1,000 sats = KES 25"}
                </div>
                {modal === "request" && (
                  <>
                    <label className="field-label" htmlFor="grant-purpose">
                      What will this make possible?
                    </label>
                    <textarea
                      id="grant-purpose"
                      placeholder="A little more stock, a new tool, your next opportunity…"
                      value={purpose}
                      onChange={(event) => setPurpose(event.target.value)}
                      required
                      maxLength={500}
                      rows={3}
                    />
                  </>
                )}
                {modal === "repay" && (
                  <>
                    <label className="field-label" htmlFor="recovery-method">
                      Recovery method
                    </label>
                    <select
                      id="recovery-method"
                      value={repaymentMethod}
                      onChange={(event) =>
                        setRepaymentMethod(event.target.value)
                      }
                    >
                      <option value="lightning">
                        Direct Lightning recovery
                      </option>
                      <option value="otc">
                        OTC · Peter Kamau remits for you
                      </option>
                    </select>
                  </>
                )}
                <div className="form-callout">
                  <ShieldCheck size={19} />
                  <p>
                    {modal === "request"
                      ? `${clan?.policy.member_vote_quorum} member votes, then ${clan?.policy.signer_threshold} signatory approvals. Your clan decides together.`
                      : "This changes your demo treasury only. No real money moves."}
                  </p>
                </div>
                <button
                  className="primary-button"
                  type="submit"
                  disabled={
                    disabled ||
                    (modal === "repay" &&
                      selected?.beneficiary_id !== currentUser?.id)
                  }
                >
                  <Busy busy={busy}>
                    {modal === "request"
                      ? "Send request to your clan"
                      : modal === "contribute"
                        ? "Record demo contribution"
                        : "Record demo recovery"}
                  </Busy>
                  <ArrowUpRight size={18} />
                </button>
              </form>
            )}

            {modal === "create" && (
              <form onSubmit={createClan} className="create-form">
                <p className="form-intro">
                  Your people, your purpose, your shared treasury. Start with a
                  name.
                </p>
                <label className="field-label" htmlFor="clan-name">
                  Clan name
                </label>
                <input
                  id="clan-name"
                  value={newName}
                  onChange={(event) => setNewName(event.target.value)}
                  placeholder="e.g. Soweto Traders"
                  required
                  maxLength={100}
                />
                <p className="field-label">Choose an approval preset</p>
                <div
                  className="preset-options"
                  role="group"
                  aria-label="Approval preset"
                >
                  {[3, 5, 7].map((count) => (
                    <button
                      key={count}
                      type="button"
                      aria-pressed={preset === count}
                      className={preset === count ? "selected" : ""}
                      onClick={() => setPreset(count)}
                    >
                      <strong>{count}</strong>
                      <span>signatories</span>
                      <small>{(count + 1) / 2} approvals</small>
                      {preset === count && (
                        <CheckCircle size={16} weight="fill" />
                      )}
                    </button>
                  ))}
                </div>
                <div className="form-callout">
                  <ShieldCheck size={21} />
                  <p>
                    The required approval threshold is saved. Your clan starts
                    with you; invitations and assigning the signatories are the
                    next implementation step.
                  </p>
                </div>
                <button
                  className="primary-button"
                  type="submit"
                  disabled={disabled || !newName.trim()}
                >
                  <Busy busy={busy}>Create your clan</Busy>
                  <ArrowUpRight size={18} />
                </button>
                <p className="section-footnote">
                  No deposit or new Lightning channel needed.
                </p>
              </form>
            )}

            {modal === "review" && selected && (
              <GrantReview
                grant={selected}
                clan={clan!}
                currentUserId={currentUser?.id || ""}
                isSigner={isSigner}
                nameOf={nameOf}
                disabled={disabled}
                busy={busy}
                act={act}
                switchToRecipient={() => {
                  const next = session?.personas.find(
                    (user) => user.id === selected.beneficiary_id,
                  );
                  if (next) switchPersona(next.key);
                }}
                openRecovery={() => open("repay", selected)}
              />
            )}
            {modal === "recovery" && (
              <>
                <p className="form-intro">
                  Recoverable capital is still part of your clan’s story. As
                  it comes back, it can support the next member.
                </p>
                <div className="recovery-total">
                  {kes(recoveryKes)}
                  <span>Total remaining obligations</span>
                </div>
                <div className="recovery-list">
                  {recovering.length ? (
                    recovering.map((grant) => (
                      <button
                        key={grant.id}
                        onClick={() => open("review", grant)}
                      >
                        <Avatar name={nameOf(grant.beneficiary_id)} />
                        <span>
                          <strong>{nameOf(grant.beneficiary_id)}</strong>
                          <small>{grant.purpose}</small>
                        </span>
                        <b>
                          {kes(
                            grant.obligation_currency === "KES"
                              ? grant.outstanding_minor / 100
                              : demoKes(grant.outstanding_minor),
                          )}
                        </b>
                        <CaretRight size={15} />
                      </button>
                    ))
                  ) : (
                    <div className="empty-inline">
                      <CheckCircle size={30} />
                      <p>No grants in recovery yet.</p>
                    </div>
                  )}
                </div>
                <p className="section-footnote">
                  Obligations and available treasury balance are tracked
                  separately.
                </p>
              </>
            )}
            {modal === "clans" && (
              <div className="clan-picker">
                {clans.map((item) => (
                  <button
                    key={item.id}
                    disabled={disabled}
                    onClick={() => selectClan(item)}
                  >
                    <span className="action-icon">
                      <UsersThree size={23} />
                    </span>
                    <span>
                      <strong>{item.name}</strong>
                      <small>
                        {item.member_count}{" "}
                        {item.member_count === 1 ? "member" : "members"} ·{" "}
                        {item.policy.signer_threshold} approvals required
                      </small>
                    </span>
                    {item.id === clan?.id ? (
                      <CheckCircle size={21} weight="fill" />
                    ) : (
                      <CaretRight size={17} />
                    )}
                  </button>
                ))}
                <button
                  className="secondary-button full-width"
                  onClick={() => open("create")}
                >
                  <Plus size={18} />
                  Start a new clan
                </button>
              </div>
            )}
            {modal === "notifications" && (
              <div className="notification-list">
                {pendingGrants.length ? (
                  pendingGrants.map((grant) => (
                    <button
                      key={grant.id}
                      onClick={() => open("review", grant)}
                    >
                      <span className="action-icon">
                        <FileText size={23} />
                      </span>
                      <span>
                        <strong>Your voice matters.</strong>
                        <small>
                          {nameOf(grant.beneficiary_id).split(" ")[0]} has a{" "}
                          {kes(demoKes(grant.amount_sats))} grant request.{" "}
                          {statusLabels[grant.status]}.
                        </small>
                      </span>
                      <CaretRight size={18} />
                    </button>
                  ))
                ) : (
                  <div className="empty-inline">
                    <CheckCircle size={32} />
                    <p>You’re all caught up.</p>
                    <span>We’ll keep you in the loop.</span>
                  </div>
                )}
              </div>
            )}
          </Sheet>
        )}
        {toast && (
          <div className="toast" role="status">
            <CheckCircle size={20} weight="fill" />
            <span>{toast}</span>
          </div>
        )}
        {error && !modal && clan && (
          <div className="inline-error" role="alert">
            {error}
            <button onClick={() => setError("")}>Dismiss</button>
          </div>
        )}
      </div>
    </div>
  );
}

function ActivityRow({ event, name }: { event: SimEvent; name: string }) {
  const incoming = event.action === "contribute" || event.action === "repay";
  return (
    <div className="activity-row">
      <span className={`activity-icon ${incoming ? "incoming" : ""}`}>
        {incoming ? (
          <ArrowDownLeft size={20} />
        ) : event.action.includes("vote") ||
          event.action.includes("approve") ? (
          <ShieldCheck size={20} />
        ) : (
          <FileText size={20} />
        )}
      </span>
      <div>
        <strong>{labels[event.action] || event.action}</strong>
        <span>{name}</span>
      </div>
      <span className="activity-kind">
        {incoming ? "Received" : "Recorded"}
      </span>
    </div>
  );
}

function GrantReview({
  grant,
  clan,
  currentUserId,
  isSigner,
  nameOf,
  disabled,
  busy,
  act,
  switchToRecipient,
  openRecovery,
}: {
  grant: Grant;
  clan: Clan;
  currentUserId: string;
  isSigner: boolean;
  nameOf: (id: string) => string;
  disabled: boolean;
  busy: boolean;
  act: (
    body: Record<string, unknown>,
    message: string,
    close?: boolean,
  ) => Promise<void>;
  switchToRecipient: () => void;
  openRecovery: () => void;
}) {
  const recipient = grant.beneficiary_id === currentUserId;
  const eligibleSigner =
    isSigner && grant.eligible_signer_ids.includes(currentUserId);
  const approvals = Object.values(grant.votes).filter(
    (vote) => vote === "approve",
  ).length;
  const expired = grant.intent
    ? Date.now() >= Date.parse(grant.intent.expires_at)
    : false;
  const send = (
    action: string,
    extra = {},
    message = "Your decision has been recorded.",
  ) => act({ action, grant_id: grant.id, ...extra }, message);
  return (
    <div className="grant-review">
      <div className="review-person">
        <Avatar name={nameOf(grant.beneficiary_id)} />
        <span>
          <strong>{nameOf(grant.beneficiary_id)}</strong>
          <small>Recoverable grant request</small>
        </span>
        <span className="decision-pill">{statusLabels[grant.status]}</span>
      </div>
      <div className="review-amount">{kes(demoKes(grant.amount_sats))}</div>
      <p className="review-purpose">{grant.purpose}</p>
      <div className="review-details">
        <div>
          <span>Recovery target</span>
          <strong>
            {grant.obligation_currency === "KES"
              ? kes(grant.principal_minor / 100)
              : satsLabel(grant.principal_minor)}
          </strong>
        </div>
        <div>
          <span>Member decision</span>
          <strong>
            {approvals} of {clan.policy.member_vote_quorum} votes
          </strong>
        </div>
        <div>
          <span>Signatory approval</span>
          <strong>
            {grant.approvals.length} of {clan.policy.signer_threshold}
          </strong>
        </div>
      </div>
      <div className="vote-people">
        {grant.eligible_voter_ids.map((id) => (
          <span
            key={id}
            className={grant.votes[id] === "approve" ? "voted" : ""}
            title={`${nameOf(id)}: ${grant.votes[id] || "Not voted"}`}
          >
            <Avatar name={nameOf(id)} small />
            {grant.votes[id] === "approve" && (
              <CheckCircle size={14} weight="fill" />
            )}
          </span>
        ))}
      </div>
      {grant.status === "voting" &&
        (grant.eligible_voter_ids.includes(currentUserId) &&
        !grant.votes[currentUserId] ? (
          <div className="review-actions">
            <button
              className="primary-button"
              disabled={disabled}
              onClick={() =>
                send(
                  "vote",
                  { choice: "approve" },
                  "Your vote is in. Your circle moves forward together.",
                )
              }
            >
              <Busy busy={busy}>
                <Check size={19} />
                Approve request
              </Busy>
            </button>
            <button
              className="secondary-button"
              disabled={disabled}
              onClick={() => send("vote", { choice: "reject" })}
            >
              Decline
            </button>
          </div>
        ) : (
          <div className="notice">
            {recipient
              ? "Your clan is reviewing your request. Recipients do not vote on their own grant."
              : "Your vote is recorded. The remaining eligible members can now decide."}
          </div>
        ))}
      {grant.status === "accepted" &&
        (recipient ? (
          <button
            className="primary-button"
            disabled={disabled}
            onClick={() =>
              send(
                "accept_terms",
                {},
                "Recovery terms accepted. Ready for signatories.",
              )
            }
          >
            <Busy busy={busy}>Accept recovery terms</Busy>
          </button>
        ) : (
          <div className="notice">
            <p>
              The member vote passed.{" "}
              {nameOf(grant.beneficiary_id).split(" ")[0]} must accept the
              recovery terms.
            </p>
            <button
              className="text-button"
              disabled={disabled}
              onClick={switchToRecipient}
            >
              Demo: view as recipient
              <ArrowUpRight size={15} />
            </button>
          </div>
        ))}
      {(grant.status === "terms_accepted" ||
        (["awaiting_signers", "authorized"].includes(grant.status) &&
          expired)) &&
        (eligibleSigner ? (
          <button
            className="primary-button"
            disabled={disabled}
            onClick={() =>
              send(
                "freeze_intent",
                { destination: `sim:${grant.id}`, fee_ceiling_sats: 10 },
                "Exact demo payment details are ready for signatories.",
              )
            }
          >
            <Busy busy={busy}>
              {expired
                ? "Renew expired approval request"
                : "Prepare signatory approval"}
            </Busy>
          </button>
        ) : (
          <div className="notice">
            An eligible signatory can prepare this grant for approval.
          </div>
        ))}
      {["awaiting_signers", "authorized"].includes(grant.status) &&
        !expired &&
        grant.intent && (
          <>
            <div className="intent-summary">
              <ShieldCheck size={20} />
              <p>
                Approvals cover this grant’s recipient, amount, destination,
                policy, expiry and a 10-sat maximum fee.
              </p>
            </div>
            {grant.status === "awaiting_signers" &&
              (eligibleSigner && !grant.approvals.includes(currentUserId) ? (
                <button
                  className="primary-button"
                  disabled={disabled}
                  onClick={() =>
                    send(
                      "approve_intent",
                      { intent_sha256: grant.intent!.sha256 },
                      "Your signatory approval is recorded.",
                    )
                  }
                >
                  <Busy busy={busy}>Approve exact demo payment</Busy>
                </button>
              ) : (
                <div className="notice">
                  {grant.approvals.includes(currentUserId)
                    ? "Your approval is recorded. Another independent signatory must approve."
                    : "Waiting for the required eligible signatories."}
                </div>
              ))}
            {grant.status === "authorized" && eligibleSigner && (
              <button
                className="primary-button"
                disabled={disabled}
                onClick={() =>
                  send(
                    "execute",
                    { intent_sha256: grant.intent!.sha256, actual_fee_sats: 2 },
                    "Demo grant issued. Your community capital is at work.",
                  )
                }
              >
                <Busy busy={busy}>Complete demo grant</Busy>
                <ArrowUpRight size={18} />
              </button>
            )}
          </>
        )}
      {grant.status === "settled_simulated" && (
        <>
          <div className="notice">
            <strong>
              {grant.obligation_currency === "KES"
                ? kes(grant.outstanding_minor / 100)
                : satsLabel(grant.outstanding_minor)}{" "}
              remaining
            </strong>
            <p>
              {kes(demoKes(grant.recovered_sats))} recovered to the demo
              treasury.
            </p>
          </div>
          {grant.outstanding_minor > 0 && (
            <button
              className="primary-button"
              disabled={disabled || !recipient}
              onClick={openRecovery}
            >
              Make a recovery payment
              <ArrowUpRight size={18} />
            </button>
          )}
          {!recipient && (
            <button
              className="text-button"
              disabled={disabled}
              onClick={switchToRecipient}
            >
              Demo: view as recipient
              <ArrowUpRight size={15} />
            </button>
          )}
        </>
      )}
      <p className="section-footnote">
        Interactive demo. Decisions and balances are saved to the test treasury.
        No real payments.
      </p>
    </div>
  );
}
