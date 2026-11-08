import type { Clan, Member, Run, Session } from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

export async function request<T>(
  path: string,
  persona = "chair",
  body?: unknown,
  key?: string,
): Promise<T> {
  const response = await fetch(`/__demo${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Demo-Persona": persona,
      ...(body !== undefined
        ? { "Idempotency-Key": key || crypto.randomUUID() }
        : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(15000),
    cache: "no-store",
  });
  const data = await response.json().catch(() => null);
  if (!response.ok)
    throw new ApiError(
      data?.error?.message ||
        "Could not complete that action. Please try again.",
      response.status,
    );
  return data as T;
}

export async function getSession(): Promise<Session> {
  const response = await fetch("/__demo/session", {
    cache: "no-store",
    signal: AbortSignal.timeout(10000),
  });
  if (!response.ok)
    throw new Error(
      "Start the local demo backend to use interactive features.",
    );
  return response.json();
}

export async function getDashboard(
  clanId: string,
  runId: string,
  persona: string,
) {
  const base = `/api/v1/clans/${clanId}`;
  const [clan, members, run] = await Promise.all([
    request<Clan>(base, persona),
    request<Member[]>(`${base}/members`, persona),
    request<Run>(`${base}/simulations/${runId}`, persona),
  ]);
  return { clan, members, run };
}

export function command(
  clanId: string,
  runId: string,
  persona: string,
  body: Record<string, unknown>,
  key: string,
) {
  return request<Run>(
    `/api/v1/clans/${clanId}/simulations/${runId}/commands`,
    persona,
    body,
    key,
  );
}
