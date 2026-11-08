// This adapter contains no encryption or key storage. The backend team owns store.ts.
export type Unlock = { kind: "passkey" } | { kind: "pin"; pin: string };
export type Protection = "passkey" | "pin";
export interface VaultStore {
  vaultSupport(): Promise<{ passkey: boolean; pin: true }>;
  vaultProtection(id: string): Promise<Protection | null>;
  saveVault(id: string, words: string, unlock: Unlock): Promise<void>;
  openVault(id: string, unlock: Unlock): Promise<string>;
  forgetVault(id: string): Promise<void>;
}
const stores = import.meta.glob<VaultStore>("./vault/store.ts");
export async function vaultStore(): Promise<VaultStore> {
  if (import.meta.env.DEV && location.pathname === "/__wallet_preview")
    return import("./vault/store-preview");
  const real = stores["./vault/store.ts"];
  if (real) return real();
  if (import.meta.env.DEV) return import("./vault/store-preview");
  throw Error(
    "Signing key protection is not available in this build. Please try again after the app is updated.",
  );
}
