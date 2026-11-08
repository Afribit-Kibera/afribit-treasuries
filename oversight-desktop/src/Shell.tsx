import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Bell,
  House,
  Laptop,
  ShieldCheck,
  UsersThree,
  type Icon,
} from "@phosphor-icons/react";
import { call, usingFixtures } from "./core";
import type { Clan, Overview, Status } from "./types";
import { AppContext, networks, type AppState, type Screen } from "./state";
import { Home } from "./Home";
import { Alarms } from "./Alarms";
import { Clans } from "./Clans";
import { ThisLaptop } from "./ThisLaptop";
import { PayoutFlow } from "./Payout";
import { RegisterWallet } from "./RegisterWallet";

// The server allows 120 calls an hour; a check is 4. Never check by itself more often.
const AUTO_CHECK_MS = 5 * 60 * 1000;
const FRESH_MS = 2 * 60 * 1000;

const sections: { name: "home" | "alarms" | "clans" | "laptop"; label: string; icon: Icon }[] = [
  { name: "home", label: "Home", icon: House },
  { name: "alarms", label: "Alarms", icon: Bell },
  { name: "clans", label: "Clans", icon: UsersThree },
  { name: "laptop", label: "This laptop", icon: Laptop },
];

function section(screen: Screen) {
  if (screen.name === "payout" || screen.name === "register") return "home";
  return screen.name;
}

function NetworkBand({ clans, community, server }: { clans: Clan[]; community: string | null; server: string | null }) {
  const found = networks(clans);
  const mainnet = found.includes("bitcoin");
  const test = found.some((network) => network !== "bitcoin");
  const host = server ? server.replace(/^https?:\/\//, "") : "";
  const where =
    (community ? `${community} · ` : "") +
    (host ? `Connected to ${host}` : "Not connected") +
    (usingFixtures ? " · FIXTURES (dev only)" : "");
  return (
    <div className={`network-band ${mainnet ? "band-mainnet" : test ? "band-test" : "band-unknown"}`}>
      <strong>
        {mainnet && test
          ? "Bitcoin mainnet and test network clans"
          : mainnet
            ? "Bitcoin mainnet: real money"
            : test
              ? "Test network: not real money"
              : "Network shown once a clan wallet is registered"}
      </strong>
      <span title={where}>{where}</span>
    </div>
  );
}

export function Shell({ status }: { status: Status }) {
  const [screen, setScreen] = useState<Screen>({ name: "home" });
  const [overview, setOverview] = useState<Overview | null>(null);
  const [overviewError, setOverviewError] = useState<unknown>(null);
  const [checkedAt, setCheckedAt] = useState<Date | null>(null);
  const [checking, setChecking] = useState(false);
  const [stale, setStale] = useState(true);
  const [clans, setClans] = useState<Clan[]>([]);
  const [unread, setUnread] = useState(0);
  const [flash, setFlash] = useState("");
  const running = useRef(false);

  // Throws, so the Clans screen can show the error. Other callers ignore it: the band and
  // the list just stay as they were.
  const reloadClans = useCallback(async () => {
    setClans(await call("clans"));
  }, []);

  const refresh = useCallback(async () => {
    if (running.current) return;
    running.current = true;
    setChecking(true);
    try {
      const found = await call("overview");
      setOverview(found);
      setOverviewError(null);
      if (found.answered) setUnread(found.alarms.length);
    } catch (reason) {
      setOverviewError(reason);
    } finally {
      setCheckedAt(new Date());
      setStale(false);
      setChecking(false);
      running.current = false;
    }
    void reloadClans().catch(() => undefined);
  }, [reloadClans]);

  // Home refreshes when it opens after a change, or when the last check is old.
  useEffect(() => {
    if (screen.name !== "home") return;
    const old = !checkedAt || Date.now() - checkedAt.getTime() >= FRESH_MS;
    if (stale || old) void refresh();
    const timer = setInterval(() => {
      if (document.visibilityState === "visible") void refresh();
    }, AUTO_CHECK_MS);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [screen.name, stale]);

  const go = useCallback((next: Screen) => {
    setScreen(next);
    window.scrollTo({ top: 0 });
  }, []);

  const state = useMemo<AppState>(
    () => ({
      status,
      overview,
      overviewError,
      checkedAt,
      checking,
      stale,
      clans,
      unread,
      flash,
      refresh,
      reloadClans,
      changed: () => setStale(true),
      setUnread,
      setFlash,
      go,
    }),
    [status, overview, overviewError, checkedAt, checking, stale, clans, unread, flash, refresh, reloadClans, go],
  );

  const current = section(screen);
  const community = overview?.answered ? overview.community : null;

  return (
    <AppContext.Provider value={state}>
      <div className="shell">
        <nav className="sidebar" aria-label="Main">
          <p className="sidebar-brand">
            <ShieldCheck size={26} weight="fill" aria-hidden />
            <span>
              Afribit <em>Oversight</em>
            </span>
          </p>
          <ul>
            {sections.map(({ name, label, icon: SectionIcon }) => (
              <li key={name}>
                <button
                  className={`nav-item ${current === name ? "active" : ""}`}
                  aria-current={current === name ? "page" : undefined}
                  onClick={() => go({ name })}
                >
                  <SectionIcon size={22} weight={current === name ? "fill" : "regular"} aria-hidden />
                  <span>{label}</span>
                  {name === "alarms" && unread > 0 && (
                    <span className="nav-badge" aria-label={`${unread} new`}>
                      {unread}
                    </span>
                  )}
                </button>
              </li>
            ))}
          </ul>
          <p className="sidebar-foot">Nothing is signed without your passphrase.</p>
        </nav>
        <div className="main-column">
          <NetworkBand clans={clans} community={community} server={status.server} />
          <main className="content">
            {screen.name === "home" && <Home />}
            {screen.name === "alarms" && <Alarms />}
            {screen.name === "clans" && <Clans />}
            {screen.name === "laptop" && <ThisLaptop />}
            {screen.name === "payout" && <PayoutFlow key={screen.id} payoutId={screen.id} />}
            {screen.name === "register" && (
              <RegisterWallet
                key={`${screen.wallet.clan_id}-${screen.wallet.generation}`}
                wallet={screen.wallet}
                onDone={() => go({ name: "home" })}
                doneLabel="Back to Home"
                onCancel={() => go({ name: "home" })}
              />
            )}
          </main>
        </div>
      </div>
    </AppContext.Provider>
  );
}
