// Keeps each clan's backup words on this phone, encrypted. Nothing here talks to the server.
//
// - Passkey: the phone's Clans passkey produces a secret through the WebAuthn PRF extension.
// - PIN: 6 to 12 digits, stretched with scrypt. This stops casual access, not someone who
//   copies the phone's storage and tries every PIN. That is accepted because a signatory key
//   can't spend alone: a payout also needs the clan majority and an Afribit oversight key.
//
// Words are encrypted with AES-GCM, bound to the clan and protection type, and stored in
// IndexedDB. Wrong PINs are slowed down after a few attempts.

import { scryptAsync } from "@noble/hashes/scrypt.js";
import { validateMnemonic } from "@scure/bip39";
import { wordlist } from "@scure/bip39/wordlists/english.js";

export type Unlock = { kind: "passkey" } | { kind: "pin"; pin: string };
export type Protection = "passkey" | "pin";

export class VaultLockedError extends Error {}

const VERSION = 1;
const CONTEXT = "afribit-clans-vault-v1";
const SCRYPT = { N: 2 ** 16, r: 8, p: 1 } as const;
const FREE_PIN_ATTEMPTS = 5;
const FIRST_DELAY_MS = 30_000;
const MAX_DELAY_MS = 24 * 60 * 60 * 1000;
const PASSKEY_TIMEOUT_MS = 120_000;

export type VaultRecord = {
  v: typeof VERSION;
  clanId: string;
  protection: Protection;
  salt: Uint8Array;
  iv: Uint8Array;
  data: Uint8Array;
  kdf?: { name: "scrypt"; N: number; r: number; p: number };
  credentialId?: Uint8Array;
  failures: number;
  lockedUntil: number;
};

export interface VaultBackend {
  get(clanId: string): Promise<VaultRecord | undefined>;
  put(record: VaultRecord): Promise<void>;
  delete(clanId: string): Promise<void>;
}

/** Passkey access, replaceable so the store can be checked outside a browser. */
export interface PasskeySecret {
  /** Returns the PRF output for `salt`, and the credential that produced it. */
  derive(salt: Uint8Array, credentialId?: Uint8Array): Promise<{ secret: Uint8Array; credentialId: Uint8Array }>;
}

const encoder = new TextEncoder();
const decoder = new TextDecoder();
const random = (length: number) => crypto.getRandomValues(new Uint8Array(length));
const buffer = (bytes: Uint8Array) => bytes.slice().buffer as ArrayBuffer;

// ---------- storage ----------

const DB_NAME = "afribit-clans-vault";
const STORE = "vaults";

function request<T>(req: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

let database: Promise<IDBDatabase> | undefined;

function openDatabase(): Promise<IDBDatabase> {
  database ??= new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE, { keyPath: "clanId" });
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => {
      database = undefined;
      reject(req.error);
    };
  });
  return database;
}

const indexedDbBackend: VaultBackend = {
  async get(clanId) {
    const db = await openDatabase();
    return request(db.transaction(STORE).objectStore(STORE).get(clanId));
  },
  async put(record) {
    const db = await openDatabase();
    await request(db.transaction(STORE, "readwrite").objectStore(STORE).put(record));
  },
  async delete(clanId) {
    const db = await openDatabase();
    await request(db.transaction(STORE, "readwrite").objectStore(STORE).delete(clanId));
  },
};

// ---------- passkey ----------

type PrfResults = { prf?: { results?: { first?: BufferSource } } };

const browserPasskey: PasskeySecret = {
  async derive(salt, credentialId) {
    let credential: PublicKeyCredential | null;
    try {
      credential = (await navigator.credentials.get({
        publicKey: {
          // Local only: the result is never sent to a server, so a local challenge is enough.
          challenge: buffer(random(32)),
          allowCredentials: credentialId ? [{ type: "public-key", id: buffer(credentialId) }] : [],
          userVerification: "required",
          timeout: PASSKEY_TIMEOUT_MS,
          extensions: { prf: { eval: { first: buffer(salt) } } } as AuthenticationExtensionsClientInputs,
        },
      })) as PublicKeyCredential | null;
    } catch {
      throw new VaultLockedError("The passkey check was cancelled. Try again.");
    }
    if (!credential) throw new VaultLockedError("The passkey check was cancelled. Try again.");
    const first = (credential.getClientExtensionResults() as PrfResults).prf?.results?.first;
    if (!first) {
      throw new VaultLockedError("This passkey can't protect your signing key. Use a PIN instead.");
    }
    const bytes = first instanceof ArrayBuffer ? first : first.buffer;
    return { secret: new Uint8Array(bytes.slice(0)), credentialId: new Uint8Array(credential.rawId) };
  },
};

let backend: VaultBackend = indexedDbBackend;
let passkey: PasskeySecret = browserPasskey;

/** For checks outside a browser only. */
export function setVaultEnvironment(options: { backend?: VaultBackend; passkey?: PasskeySecret }): void {
  if (options.backend) backend = options.backend;
  if (options.passkey) passkey = options.passkey;
}

// ---------- keys ----------

function associatedData(clanId: string, protection: Protection): Uint8Array {
  return encoder.encode(`${CONTEXT}|${clanId}|${protection}`);
}

async function aesKey(material: Uint8Array, salt: Uint8Array, protection: Protection): Promise<CryptoKey> {
  const base = await crypto.subtle.importKey("raw", buffer(material), "HKDF", false, ["deriveKey"]);
  return crypto.subtle.deriveKey(
    { name: "HKDF", hash: "SHA-256", salt: buffer(salt), info: buffer(encoder.encode(`${CONTEXT}|${protection}`)) },
    base,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"],
  );
}

function checkPin(pin: string): void {
  if (!/^\d{6,12}$/.test(pin)) throw new VaultLockedError("Use a PIN with 6 to 12 digits.");
}

async function pinMaterial(pin: string, salt: Uint8Array, kdf: VaultRecord["kdf"]) {
  const { N, r, p } = kdf ?? SCRYPT;
  return scryptAsync(encoder.encode(pin), salt, { N, r, p, dkLen: 32 });
}

// ---------- public interface ----------

/** Which protections this device supports. Passkey needs WebAuthn PRF support. */
export async function vaultSupport(): Promise<{ passkey: boolean; pin: true }> {
  let prf = false;
  try {
    const credentials = globalThis.PublicKeyCredential as
      | (typeof PublicKeyCredential & { getClientCapabilities?: () => Promise<Record<string, boolean>> })
      | undefined;
    if (globalThis.isSecureContext && credentials?.getClientCapabilities) {
      prf = (await credentials.getClientCapabilities())["extension:prf"] === true;
    }
  } catch {
    prf = false;
  }
  return { passkey: prf, pin: true };
}

/** How this phone protects the clan's key, or null when this phone has no key for the clan. */
export async function vaultProtection(clanId: string): Promise<Protection | null> {
  return (await backend.get(clanId))?.protection ?? null;
}

/** Encrypts the backup words on this phone, replacing any key already saved for the clan. */
export async function saveVault(clanId: string, words: string, unlock: Unlock): Promise<void> {
  const normalized = words.trim().toLowerCase().split(/\s+/).join(" ");
  if (!validateMnemonic(normalized, wordlist)) throw new VaultLockedError("These backup words are not valid.");
  const salt = random(32);
  let material: Uint8Array;
  let credentialId: Uint8Array | undefined;
  let kdf: VaultRecord["kdf"];
  if (unlock.kind === "pin") {
    checkPin(unlock.pin);
    kdf = { name: "scrypt", ...SCRYPT };
    material = await pinMaterial(unlock.pin, salt, kdf);
  } else {
    ({ secret: material, credentialId } = await passkey.derive(salt));
  }
  const key = await aesKey(material, salt, unlock.kind);
  material.fill(0);
  const iv = random(12);
  const data = new Uint8Array(
    await crypto.subtle.encrypt(
      { name: "AES-GCM", iv: buffer(iv), additionalData: buffer(associatedData(clanId, unlock.kind)) },
      key,
      buffer(encoder.encode(normalized)),
    ),
  );
  await backend.put({
    v: VERSION,
    clanId,
    protection: unlock.kind,
    salt,
    iv,
    data,
    kdf,
    credentialId,
    failures: 0,
    lockedUntil: 0,
  });
  // Ask the browser not to clear this storage under pressure. Backup words remain the real backup.
  await navigator.storage?.persist?.().catch(() => false);
}

/** Returns the backup words. Throws VaultLockedError on a wrong PIN or cancelled passkey. */
export async function openVault(clanId: string, unlock: Unlock): Promise<string> {
  const record = await backend.get(clanId);
  if (!record || record.v !== VERSION) {
    throw new VaultLockedError("There's no signing key for this clan on this phone.");
  }
  if (unlock.kind !== record.protection) {
    throw new VaultLockedError(
      record.protection === "pin" ? "Unlock with your PIN." : "Unlock with your passkey.",
    );
  }
  const now = Date.now();
  if (record.lockedUntil > now) {
    const minutes = Math.ceil((record.lockedUntil - now) / 60_000);
    throw new VaultLockedError(`Too many wrong PINs. Try again in ${minutes} minute${minutes === 1 ? "" : "s"}.`);
  }
  let material: Uint8Array;
  if (unlock.kind === "pin") {
    checkPin(unlock.pin);
    material = await pinMaterial(unlock.pin, record.salt, record.kdf);
  } else {
    ({ secret: material } = await passkey.derive(record.salt, record.credentialId));
  }
  const key = await aesKey(material, record.salt, record.protection);
  material.fill(0);
  try {
    const plain = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv: buffer(record.iv), additionalData: buffer(associatedData(clanId, record.protection)) },
      key,
      buffer(record.data),
    );
    if (record.failures) await backend.put({ ...record, failures: 0, lockedUntil: 0 });
    return decoder.decode(plain);
  } catch {
    if (record.protection === "passkey") {
      throw new VaultLockedError("This passkey doesn't unlock the key. Use the passkey you set it up with.");
    }
    const failures = record.failures + 1;
    const extra = failures - FREE_PIN_ATTEMPTS;
    const lockedUntil = extra >= 0 ? now + Math.min(FIRST_DELAY_MS * 2 ** extra, MAX_DELAY_MS) : 0;
    await backend.put({ ...record, failures, lockedUntil });
    throw new VaultLockedError("Wrong PIN. Check it and try again.");
  }
}

/** Removes this clan's key from this phone. The backup words can restore it. */
export async function forgetVault(clanId: string): Promise<void> {
  await backend.delete(clanId);
}
