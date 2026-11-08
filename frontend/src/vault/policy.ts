// Clan wallet rules, computed on the signatory's own device.
// Must produce exactly the same wallet as backend/src/clans/clan_wallet.py.
// The phone uses this to check every address and payment itself instead of trusting the server.

import { sha256 } from "@noble/hashes/sha2.js";
import { hexToBytes, utf8ToBytes } from "@noble/hashes/utils.js";
import { HDKey } from "@scure/bip32";
import { NETWORK, p2tr, Script, TEST_NETWORK } from "@scure/btc-signer";

// BIP-341 point with no known private key: the key path can never be used. Each wallet
// uses it as an extended key with its own chain code, like the backend.
export const UNSPENDABLE_KEY = "50929b74c1a04954b78b4b6035e97a5e078a5a0f28ec96d547bfee9ace803ac0";
const UNSPENDABLE_TAG = "Afribit Clans unspendable key v1";
export const ACCOUNT_PATH = "87'/1'/0'";
export const MAINNET_ACCOUNT_PATH = "87'/0'/0'";
export const NETWORKS = ["signet", "testnet4", "bitcoin"] as const;
export type ClanNetwork = (typeof NETWORKS)[number];
export const MAJORITY: Record<number, number> = { 3: 2, 5: 3, 7: 4 };
export const MAX_OVERSIGHT_KEYS = 3;
export const DEFAULT_RECOVERY_BLOCKS = 26_280;
const MIN_RECOVERY_BLOCKS = 4_320;
const MAX_RECOVERY_BLOCKS = 65_535;

export const TEST_VERSIONS = { private: 0x04358394, public: 0x043587cf };
export const MAIN_VERSIONS = { private: 0x0488ade4, public: 0x0488b21e };

/** Test networks share coin type 1 and tpub keys. Bitcoin mainnet uses coin type 0 and xpub. */
export function networkRules(network: ClanNetwork) {
  return network === "bitcoin"
    ? { path: MAINNET_ACCOUNT_PATH, versions: MAIN_VERSIONS, addresses: NETWORK }
    : { path: ACCOUNT_PATH, versions: TEST_VERSIONS, addresses: TEST_NETWORK };
}

function keyVersions(xpub: string) {
  return xpub.startsWith("xpub") ? MAIN_VERSIONS : TEST_VERSIONS;
}
// Normal spending branch first, then the recovery branch for the same keychain.
export const BRANCHES = { external: [0, 2], internal: [1, 3] } as const;
export type Keychain = keyof typeof BRANCHES;

export type SignerKeyInfo = { fingerprint: string; path: string; xpub: string };

export type ClanPolicy = {
  network: ClanNetwork;
  /** Afribit's oversight keys, in the configured order. Any one of them can approve. */
  oversight: SignerKeyInfo[];
  signers: SignerKeyInfo[];
  recoveryThreshold: number;
  recoveryBlocks: number;
};

export class ClanWalletError extends Error {}

const KEY_PATTERN = /^\[([0-9a-f]{8})\/([0-9h']+(?:\/[0-9h']+)*)\]([tx]pub[1-9A-HJ-NP-Za-km-z]+)$/;

export function parseKey(value: string): SignerKeyInfo {
  const match = KEY_PATTERN.exec(value.trim());
  if (!match) throw new ClanWalletError("Expected a public key with its origin");
  const path = match[2].replaceAll("h", "'");
  const expected = match[3].startsWith("xpub") ? MAINNET_ACCOUNT_PATH : ACCOUNT_PATH;
  if (path !== expected) throw new ClanWalletError("Signer keys must use the clan account path");
  try {
    HDKey.fromExtendedKey(match[3], keyVersions(match[3]));
  } catch {
    throw new ClanWalletError("The public key is not valid");
  }
  return { fingerprint: match[1], path, xpub: match[3] };
}

export function keyExpression(key: SignerKeyInfo): string {
  return `[${key.fingerprint}/${key.path}]${key.xpub}`;
}

export function threshold(policy: ClanPolicy): number {
  return MAJORITY[policy.signers.length];
}

export function validatePolicy(policy: ClanPolicy): void {
  if (!NETWORKS.includes(policy.network)) throw new ClanWalletError("This phone cannot check this wallet's network");
  if (!MAJORITY[policy.signers.length]) throw new ClanWalletError("A clan needs 3, 5 or 7 signatories");
  if (policy.oversight.length < 1 || policy.oversight.length > MAX_OVERSIGHT_KEYS)
    throw new ClanWalletError("A clan wallet needs one to three Afribit oversight keys");
  const everyone = [...policy.oversight, ...policy.signers];
  for (const key of everyone) parseKey(keyExpression(key));
  if (everyone.some((key) => key.xpub.startsWith("xpub") !== (policy.network === "bitcoin")))
    throw new ClanWalletError("Every key must be made for this wallet's network");
  if (new Set(everyone.map((key) => key.xpub)).size !== everyone.length)
    throw new ClanWalletError("Every signatory and the oversight key must be different");
  if (new Set(everyone.map((key) => key.fingerprint)).size !== everyone.length)
    throw new ClanWalletError("Every key must come from a different recovery phrase");
  if (policy.recoveryThreshold < threshold(policy) || policy.recoveryThreshold > policy.signers.length)
    throw new ClanWalletError("Recovery needs at least the normal signatory majority");
  if (policy.recoveryBlocks < MIN_RECOVERY_BLOCKS || policy.recoveryBlocks > MAX_RECOVERY_BLOCKS)
    throw new ClanWalletError("The recovery wait must be between about 30 days and 15 months");
}

function unspendableAccount(policy: ClanPolicy): HDKey {
  const roster = [...policy.oversight, ...policy.signers].map(keyExpression).join("\n");
  return new HDKey({
    versions: networkRules(policy.network).versions,
    chainCode: sha256(utf8ToBytes(UNSPENDABLE_TAG + roster)),
    publicKey: hexToBytes("02" + UNSPENDABLE_KEY),
  });
}

/** The wallet's unspendable internal key, as an extended public key. */
export function unspendableKey(policy: ClanPolicy): string {
  return unspendableAccount(policy).publicExtendedKey;
}

/** The public descriptor, character for character the same as the backend's. */
export function descriptor(policy: ClanPolicy, keychain: Keychain): string {
  const [normal, recovery] = BRANCHES[keychain];
  const signers = policy.signers.map((key) => `${keyExpression(key)}/${normal}/*`).join(",");
  const recovering = policy.signers.map((key) => `${keyExpression(key)}/${recovery}/*`).join(",");
  const approval =
    policy.oversight.length === 1
      ? `v:pk(${keyExpression(policy.oversight[0])}/${normal}/*)`
      : `v:multi_a(1,${policy.oversight.map((key) => `${keyExpression(key)}/${normal}/*`).join(",")})`;
  return (
    `tr(${unspendableKey(policy)}/${normal}/*,{` +
    `and_v(${approval},multi_a(${threshold(policy)},${signers})),` +
    `and_v(v:multi_a(${policy.recoveryThreshold},${recovering}),older(${policy.recoveryBlocks}))})`
  );
}

/** Short code all signatories compare to confirm they hold the same wallet (BIP-380 checksum). */
export function walletCode(policy: ClanPolicy): string {
  return descriptorChecksum(descriptor(policy, "external"));
}

function childKey(key: SignerKeyInfo, branch: number, index: number): Uint8Array {
  const account = HDKey.fromExtendedKey(key.xpub, keyVersions(key.xpub));
  const child = account.deriveChild(branch).deriveChild(index);
  if (!child.publicKey) throw new ClanWalletError("Could not derive a public key");
  return child.publicKey.slice(1); // x-only key for Taproot scripts
}

export type ClanOutput = {
  address: string;
  script: Uint8Array;
  normalLeaf: Uint8Array;
  recoveryLeaf: Uint8Array;
};

/** The clan's address at one position, rebuilt from public keys alone. */
export function clanOutput(policy: ClanPolicy, keychain: Keychain, index: number): ClanOutput {
  validatePolicy(policy);
  if (!Number.isInteger(index) || index < 0 || index >= 2 ** 31) throw new ClanWalletError("Invalid address index");
  const [normal, recovery] = BRANCHES[keychain];
  const multi = (keys: Uint8Array[], required: number, verify: boolean) => [
    keys[0],
    "CHECKSIG" as const,
    ...keys.slice(1).flatMap((key) => [key, "CHECKSIGADD" as const]),
    required,
    verify ? ("NUMEQUALVERIFY" as const) : ("NUMEQUAL" as const),
  ];
  // One Afribit approval: a single key, or any one of several keys.
  const approvers = policy.oversight.map((key) => childKey(key, normal, index));
  const approval = approvers.length === 1 ? [approvers[0], "CHECKSIGVERIFY" as const] : multi(approvers, 1, true);
  const normalLeaf = Script.encode([
    ...approval,
    ...multi(policy.signers.map((key) => childKey(key, normal, index)), threshold(policy), false),
  ]);
  const recoveryLeaf = Script.encode([
    ...multi(policy.signers.map((key) => childKey(key, recovery, index)), policy.recoveryThreshold, true),
    policy.recoveryBlocks,
    "CHECKSEQUENCEVERIFY",
  ]);
  const internal = unspendableAccount(policy).deriveChild(normal).deriveChild(index).publicKey;
  if (!internal) throw new ClanWalletError("Could not derive the wallet key");
  const payment = p2tr(internal.slice(1), [{ script: normalLeaf }, { script: recoveryLeaf }], networkRules(policy.network).addresses, true);
  if (!payment.address) throw new ClanWalletError("Could not build the clan address");
  return { address: payment.address, script: payment.script, normalLeaf, recoveryLeaf };
}

// BIP-380 descriptor checksum.
const INPUT_CHARSET =
  "0123456789()[],'/*abcdefgh@:$%{}IJKLMNOPQRSTUVWXYZ&+-.;<=>?!^_|~ijklmnopqrstuvwxyzABCDEFGH`#\"\\ ";
const CHECKSUM_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l";
const GENERATOR = [0xf5dee51989n, 0xa9fdca3312n, 0x1bab10e32dn, 0x3706b1677an, 0x644d626ffdn];

function polymod(symbols: number[]): bigint {
  let checksum = 1n;
  for (const value of symbols) {
    const top = checksum >> 35n;
    checksum = ((checksum & 0x7ffffffffn) << 5n) ^ BigInt(value);
    for (let i = 0; i < 5; i++) if ((top >> BigInt(i)) & 1n) checksum ^= GENERATOR[i];
  }
  return checksum;
}

export function descriptorChecksum(text: string): string {
  const symbols: number[] = [];
  let groups: number[] = [];
  for (const character of text) {
    const value = INPUT_CHARSET.indexOf(character);
    if (value < 0) throw new ClanWalletError("Unexpected character in descriptor");
    symbols.push(value & 31);
    groups.push(value >> 5);
    if (groups.length === 3) {
      symbols.push(groups[0] * 9 + groups[1] * 3 + groups[2]);
      groups = [];
    }
  }
  if (groups.length === 1) symbols.push(groups[0]);
  if (groups.length === 2) symbols.push(groups[0] * 3 + groups[1]);
  const checksum = polymod([...symbols, 0, 0, 0, 0, 0, 0, 0, 0]) ^ 1n;
  let result = "";
  for (let i = 0; i < 8; i++) result += CHECKSUM_CHARSET[Number((checksum >> BigInt(5 * (7 - i))) & 31n)];
  return result;
}
