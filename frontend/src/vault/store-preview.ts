// Development only. Never persistent; never imported by a production build.
export type Unlock = { kind: "passkey" } | { kind: "pin"; pin: string };
export type Protection = "passkey" | "pin";
export class VaultLockedError extends Error {}
const memory = new Map<string, { words: string; unlock: Unlock }>();
export async function vaultSupport(): Promise<{ passkey: boolean; pin: true }> {
  return { passkey: false, pin: true };
}
export async function vaultProtection(id: string): Promise<Protection | null> {
  return memory.get(id)?.unlock.kind ?? null;
}
export async function saveVault(
  id: string,
  words: string,
  unlock: Unlock,
): Promise<void> {
  if (unlock.kind !== "pin" || !/^\d{6,12}$/.test(unlock.pin))
    throw new VaultLockedError("Use a PIN with 6 to 12 digits.");
  memory.set(id, { words, unlock: { ...unlock } });
}
export async function openVault(id: string, unlock: Unlock): Promise<string> {
  const value = memory.get(id);
  if (
    !value ||
    unlock.kind !== value.unlock.kind ||
    (unlock.kind === "pin" &&
      value.unlock.kind === "pin" &&
      unlock.pin !== value.unlock.pin)
  )
    throw new VaultLockedError(
      "The key is locked. Check your PIN and try again.",
    );
  return value.words;
}
export async function forgetVault(id: string): Promise<void> {
  memory.delete(id);
}
