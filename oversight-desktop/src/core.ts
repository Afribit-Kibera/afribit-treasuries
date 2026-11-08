// The one way the screens reach the oversight core (backend/src/clans/oversight_service.py).
//
// In the app, the Rust shell forwards `core` calls to the bundled Python core. In dev, Vite's
// /__core bridge does the same (see vite.config.ts). With ?fixtures in dev, answers come from
// src/fixtures.ts instead; that branch is removed from the production build.
//
// Never log the arguments: they can hold the passphrase or the backup words.

import { invoke } from "@tauri-apps/api/core";
import type { Command, Commands } from "./types";

export type CoreCode = "check" | "refused" | "internal" | "core_stopped";

/** Which check failed, when the core says (oversight_service.Check). */
export type CheckReason =
  | "wrong_passphrase"
  | "bad_words"
  | "code_mismatch"
  | "address_mismatch"
  | "payout_changed"
  | "payout_gone"
  | "alarms_unread"
  | "wrong_total";

export class CoreError extends Error {
  readonly code: CoreCode;
  readonly reason: CheckReason | null;
  constructor(message: string, code: CoreCode, reason: CheckReason | null = null) {
    super(message);
    this.name = "CoreError";
    this.code = code;
    this.reason = reason;
  }
}

const codes: CoreCode[] = ["check", "refused", "internal", "core_stopped"];

function asCoreError(reason: unknown): CoreError {
  if (reason instanceof CoreError) return reason;
  if (reason && typeof reason === "object" && "error" in reason) {
    const { error, code, reason: why } = reason as { error: unknown; code: unknown; reason?: unknown };
    return new CoreError(
      typeof error === "string" ? error : "The core sent an unreadable answer",
      codes.includes(code as CoreCode) ? (code as CoreCode) : "internal",
      typeof why === "string" ? (why as CheckReason) : null,
    );
  }
  return new CoreError(typeof reason === "string" ? reason : "The core didn't answer", "internal");
}

type Answer = (command: string, args: object) => Promise<unknown>;

let fixtures: Promise<Answer> | null = null;
if (import.meta.env.DEV && new URLSearchParams(location.search).has("fixtures")) {
  fixtures = import("./fixtures").then((module) => module.answer);
}

/** True when the screens are answered from fixed test data (dev only). */
export const usingFixtures = import.meta.env.DEV && fixtures !== null;

async function viaDevBridge(command: string, args: object): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch("/__core", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ command, args }),
      cache: "no-store",
    });
  } catch {
    throw new CoreError("The dev bridge didn't answer", "core_stopped");
  }
  let reply: { ok?: boolean; result?: unknown; error?: unknown; code?: unknown; reason?: unknown };
  try {
    reply = await response.json();
  } catch {
    throw new CoreError("The dev bridge sent an unreadable answer", "internal");
  }
  if (reply.ok === true) return reply.result;
  throw asCoreError(reply);
}

export async function core<T>(command: string, args?: object): Promise<T> {
  const given = args ?? {};
  try {
    if (import.meta.env.DEV && fixtures) return (await (await fixtures)(command, given)) as T;
    if ("__TAURI_INTERNALS__" in window) return await invoke<T>("core", { command, args: given });
    if (import.meta.env.DEV) return (await viaDevBridge(command, given)) as T;
    throw new CoreError("This page only works inside the Afribit Oversight app", "core_stopped");
  } catch (reason) {
    throw asCoreError(reason);
  }
}

/** `core` with the argument and result types of each command. */
export function call<C extends Command>(
  command: C,
  ...args: Commands[C][0] extends Record<string, never> ? [] : [Commands[C][0]]
): Promise<Commands[C][1]> {
  return core<Commands[C][1]>(command, args[0]);
}

/** What to show a person for a failed call. */
export function problemText(error: unknown): string {
  const failure = asCoreError(error);
  if (failure.code === "check") return sentence(failure.message);
  if (failure.code === "refused")
    return `The core refused a request from the app: ${sentence(failure.message)} Nothing was signed. Tell the team.`;
  return "Something went wrong. Nothing was signed unless it said approved. Close and reopen the app, and tell the team.";
}

/** Core messages have no full stop; the console adds one. */
export function sentence(text: string): string {
  const trimmed = text.trim();
  return /[.!?]$/.test(trimmed) ? trimmed : `${trimmed}.`;
}

export function isCode(error: unknown, code: CoreCode) {
  return error instanceof CoreError && error.code === code;
}

/** True when a check failed for this reason. Never match on message text. */
export function isReason(error: unknown, reason: CheckReason) {
  return error instanceof CoreError && error.reason === reason;
}
