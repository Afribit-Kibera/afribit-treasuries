import { createContext, useContext } from "react";
import type { Clan, Overview, Status, WalletToRegister } from "./types";

export type Screen =
  | { name: "home" }
  | { name: "alarms" }
  | { name: "clans" }
  | { name: "laptop" }
  | { name: "payout"; id: string }
  | { name: "register"; wallet: WalletToRegister };

export interface AppState {
  status: Status;
  overview: Overview | null;
  overviewError: unknown;
  checkedAt: Date | null;
  checking: boolean;
  /** Something changed on this laptop or on Clans since the last check. */
  stale: boolean;
  clans: Clan[];
  /** Unread alarms as last seen. The core refuses approval while there are any. */
  unread: number;
  /** A message for Home after leaving a flow, such as "Nothing was signed." */
  flash: string;
  refresh: () => Promise<void>;
  reloadClans: () => Promise<void>;
  changed: () => void;
  setUnread: (count: number | ((current: number) => number)) => void;
  setFlash: (text: string) => void;
  go: (screen: Screen) => void;
}

export const AppContext = createContext<AppState | null>(null);

export function useApp(): AppState {
  const state = useContext(AppContext);
  if (!state) throw new Error("useApp outside the app");
  return state;
}

/** The networks of the clan wallets on this laptop, which is what the payments run on. */
export function networks(clans: Clan[]): string[] {
  return [...new Set(clans.map((clan) => clan.network))];
}
