// Check a clan payment on the signatory's device, then sign it.
// The phone rebuilds every clan address from the wallet it saved at setup, so a tampered
// server cannot redirect money, inflate the fee or slip in an extra output.

import { base64 } from "@scure/base";
import { HARDENED_OFFSET } from "@scure/bip32";
import { Address, OutScript, SigHash, Transaction } from "@scure/btc-signer";
import { signerFromWords } from "./keys.ts";
import {
  BRANCHES,
  ClanWalletError,
  clanOutput,
  networkRules,
  validatePolicy,
  type ClanPolicy,
  type Keychain,
} from "./policy.ts";

export type Recipient = { address: string; amountSats: bigint };
/** Who pays the network fee. "recipients" means each beneficiary receives their approved
 * amount minus an equal share of the fee (remainder to the first recipients, in order). */
export type FeePayer = "clan" | "recipients";
export type PayoutExpectation = { recipients: Recipient[]; maxFeeSats: bigint; feePaidBy?: FeePayer };

// Smallest amount a beneficiary may receive after paying the fee. Same as the backend.
export const MIN_PAYOUT_SATS = 1_000n;

/** What each recipient actually receives once the agreed party pays the fee. */
export function amountsReceived(recipients: Recipient[], feeSats: bigint, feePaidBy: FeePayer = "clan"): Recipient[] {
  if (feePaidBy === "clan") return recipients;
  if (feePaidBy !== "recipients") throw new ClanWalletError("Unknown fee payer");
  const count = BigInt(recipients.length);
  const base = feeSats / count;
  const extra = feeSats % count;
  const received = recipients.map((r, i) => ({
    address: r.address,
    amountSats: r.amountSats - base - (BigInt(i) < extra ? 1n : 0n),
  }));
  if (received.some((r) => r.amountSats < MIN_PAYOUT_SATS))
    throw new ClanWalletError("The network fee would leave a beneficiary with too little");
  return received;
}
type Inputs = { keychain: Keychain; index: number; amountSats: bigint }[];
export type PayoutReview = { feeSats: bigint; changeSats: bigint; inputs: Inputs };

/** A refresh or a move: every coin goes to one change address of a clan wallet.
 * `destination` is the phone's own saved copy of the receiving wallet: the same wallet for a
 * refresh, the clan's new wallet for a move. Never take it from the server's payout data. */
export type SweepExpectation = { destination: ClanPolicy; index: number; maxFeeSats: bigint };
export type SweepReview = { feeSats: bigint; amountSats: bigint; address: string; inputs: Inputs };

// Highest fee a phone accepts for a refresh or move, whatever the server says. Same default
// as the backend and the oversight laptop.
export const MAX_SWEEP_FEE_SATS = 10_000n;
// Change goes only to the first 1,000 change addresses, which recovery always checks.
export const MAX_CHANGE_INDEX = 1_000;

const account = (policy: ClanPolicy) =>
  [87, policy.network === "bitcoin" ? 0 : 1, 0].map((step) => step + HARDENED_OFFSET);
const TAPSCRIPT_VERSION = 0xc0;

function equal(a: Uint8Array, b: Uint8Array): boolean {
  return a.length === b.length && a.every((byte, i) => byte === b[i]);
}

function hex(bytes: Uint8Array): string {
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

type Derivation = [Uint8Array, { hashes?: Uint8Array[]; der: { fingerprint: number; path: number[] } }][];

/** Which clan address an input or change output claims to be, from its key paths. */
function position(policy: ClanPolicy, derivations: Derivation | undefined): { keychain: Keychain; index: number } | undefined {
  const fingerprints = new Set([...policy.oversight, ...policy.signers].map((key) => parseInt(key.fingerprint, 16)));
  const found = new Set<string>();
  for (const [, { der }] of derivations ?? []) {
    if (!fingerprints.has(der.fingerprint) || der.path.length !== 5) continue;
    if (!account(policy).every((step, i) => der.path[i] === step)) continue;
    const keychain = (Object.keys(BRANCHES) as Keychain[]).find((name) => BRANCHES[name][0] === der.path[3]);
    if (keychain) found.add(`${keychain}:${der.path[4]}`);
  }
  if (found.size !== 1) return undefined;
  const [keychain, index] = [...found][0].split(":");
  return { keychain: keychain as Keychain, index: Number(index) };
}

function parse(psbt: string): Transaction {
  try {
    return Transaction.fromPSBT(base64.decode(psbt));
  } catch {
    throw new ClanWalletError("The payment data is not a valid PSBT");
  }
}

function recipientScript(address: string, policy: ClanPolicy): Uint8Array {
  try {
    return OutScript.encode(Address(networkRules(policy.network).addresses).decode(address));
  } catch {
    throw new ClanWalletError("The approved destination address is not valid on this network");
  }
}

/** Every input must be a coin of this clan wallet, spent with the normal approval rule. */
function checkInputs(tx: Transaction, policy: ClanPolicy): Inputs {
  validatePolicy(policy);
  const inputs: Inputs = [];
  for (let i = 0; i < tx.inputsLength; i++) {
    const input = tx.getInput(i);
    const at = position(policy, input.tapBip32Derivation as Derivation | undefined);
    if (!at || !input.witnessUtxo) throw new ClanWalletError("A payment input does not belong to this clan wallet");
    const own = clanOutput(policy, at.keychain, at.index);
    if (!equal(input.witnessUtxo.script, own.script))
      throw new ClanWalletError("A payment input does not belong to this clan wallet");
    const normalLeaf = (input.tapLeafScript ?? []).some(([, leaf]) =>
      leaf[leaf.length - 1] === TAPSCRIPT_VERSION && equal(leaf.subarray(0, -1), own.normalLeaf),
    );
    if (!normalLeaf) throw new ClanWalletError("The payment is not using the clan's normal approval rule");
    if (input.sighashType !== undefined && input.sighashType !== SigHash.DEFAULT)
      throw new ClanWalletError("Unexpected signature type requested");
    inputs.push({ ...at, amountSats: input.witnessUtxo.amount });
  }
  if (!inputs.length) throw new ClanWalletError("The payment has no inputs");
  return inputs;
}

function review(tx: Transaction, policy: ClanPolicy, expected: PayoutExpectation): PayoutReview {
  if (!expected.recipients.length || expected.recipients.some((r) => r.amountSats <= 0n))
    throw new ClanWalletError("A payout needs at least one positive amount");
  const inputs = checkInputs(tx, policy);
  const feeSats = tx.fee;
  if (feeSats > expected.maxFeeSats) throw new ClanWalletError("The network fee is above the approved limit");
  const remaining = amountsReceived(expected.recipients, feeSats, expected.feePaidBy).map((r) => ({
    script: hex(recipientScript(r.address, policy)),
    amount: r.amountSats,
  }));
  let changeSats = 0n;
  for (let i = 0; i < tx.outputsLength; i++) {
    const output = tx.getOutput(i);
    if (!output.script || output.amount === undefined) throw new ClanWalletError("Incomplete payment output");
    const match = remaining.findIndex((r) => r.script === hex(output.script!) && r.amount === output.amount);
    if (match >= 0) {
      remaining.splice(match, 1);
      continue;
    }
    const at = position(policy, output.tapBip32Derivation as Derivation | undefined);
    if (
      at?.keychain === "internal" &&
      at.index < MAX_CHANGE_INDEX &&
      equal(clanOutput(policy, "internal", at.index).script, output.script)
    ) {
      changeSats += output.amount;
      continue;
    }
    throw new ClanWalletError("The payment sends money somewhere that was not approved");
  }
  if (remaining.length) throw new ClanWalletError("The payment is missing an approved recipient");
  return { feeSats, changeSats, inputs };
}

function reviewSweepTx(tx: Transaction, policy: ClanPolicy, expected: SweepExpectation): SweepReview {
  const inputs = checkInputs(tx, policy);
  validatePolicy(expected.destination);
  if (!Number.isSafeInteger(expected.index) || expected.index < 0 || expected.index >= MAX_CHANGE_INDEX)
    throw new ClanWalletError("The payment sends money somewhere that was not approved");
  const target = clanOutput(expected.destination, "internal", expected.index);
  const feeSats = tx.fee;
  const limit = expected.maxFeeSats < MAX_SWEEP_FEE_SATS ? expected.maxFeeSats : MAX_SWEEP_FEE_SATS;
  if (feeSats > limit) throw new ClanWalletError("The network fee is above the approved limit");
  if (tx.outputsLength !== 1) throw new ClanWalletError("A move must pay one clan address only");
  const output = tx.getOutput(0);
  if (!output.script || output.amount === undefined) throw new ClanWalletError("Incomplete payment output");
  if (!equal(output.script, target.script))
    throw new ClanWalletError("The payment sends money somewhere that was not approved");
  return { feeSats, amountSats: output.amount, address: target.address, inputs };
}

export function reviewPayout(psbt: string, policy: ClanPolicy, expected: PayoutExpectation): PayoutReview {
  return review(parse(psbt), policy, expected);
}

/** Check a refresh or move. `policy` is the saved wallet the coins come from. */
export function reviewSweep(psbt: string, policy: ClanPolicy, expected: SweepExpectation): SweepReview {
  return reviewSweepTx(parse(psbt), policy, expected);
}

/** Review, then sign the normal approval path with this signatory's key. Returns the signed copy. */
export function signPayout(psbt: string, words: string, policy: ClanPolicy, expected: PayoutExpectation): string {
  const tx = parse(psbt);
  return signInputs(tx, words, policy, review(tx, policy, expected).inputs);
}

/** Review a refresh or move, then sign it with this signatory's key for the source wallet. */
export function signSweep(psbt: string, words: string, policy: ClanPolicy, expected: SweepExpectation): string {
  const tx = parse(psbt);
  return signInputs(tx, words, policy, reviewSweepTx(tx, policy, expected).inputs);
}

function signInputs(tx: Transaction, words: string, policy: ClanPolicy, inputs: Inputs): string {
  const { info, account } = signerFromWords(words, policy.network);
  const member = [...policy.oversight, ...policy.signers].some(
    (key) => key.fingerprint === info.fingerprint && key.xpub === info.xpub,
  );
  if (!member) throw new ClanWalletError("These backup words do not belong to a signatory of this clan");
  inputs.forEach((input, i) => {
    const child = account.deriveChild(BRANCHES[input.keychain][0]).deriveChild(input.index);
    if (!child.privateKey) throw new ClanWalletError("Could not derive the signing key");
    if (!tx.signIdx(child.privateKey, i, [SigHash.DEFAULT])) throw new ClanWalletError("Could not sign the payment");
  });
  return base64.encode(tx.toPSBT());
}
