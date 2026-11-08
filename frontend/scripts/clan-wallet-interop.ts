// Checks that the phone-side wallet code agrees with the backend (BDK).
// Run by backend/tests/test_clan_wallet_interop.py: node scripts/clan-wallet-interop.ts <case.json>

import { readFileSync } from "node:fs";
import { signerFromWords } from "../src/vault/keys.ts";
import {
  clanOutput,
  descriptor,
  keyExpression,
  parseKey,
  unspendableKey,
  walletCode,
  type ClanNetwork,
  type ClanPolicy,
} from "../src/vault/policy.ts";
import {
  reviewPayout,
  reviewSweep,
  signPayout,
  signSweep,
  type PayoutExpectation,
  type SweepExpectation,
} from "../src/vault/sign.ts";

type PolicyCase = {
  network: ClanNetwork;
  oversight: string | string[];
  signers: string[];
  recoveryThreshold: number;
  recoveryBlocks: number;
};
type Case = {
  policy: PolicyCase;
  words: string[];
  psbt: string;
  recipients: { address: string; amountSats: number }[];
  maxFeeSats: number;
  feePaidBy?: "clan" | "recipients";
  tampered: Record<string, string>;
  // A refresh or move: everything to one change address of `destination`.
  sweep?: { destination: PolicyCase; index: number };
};

const input: Case = JSON.parse(readFileSync(process.argv[2], "utf8"));
const toPolicy = (item: PolicyCase): ClanPolicy => ({
  network: item.network,
  oversight: [item.oversight].flat().map(parseKey),
  signers: item.signers.map(parseKey),
  recoveryThreshold: item.recoveryThreshold,
  recoveryBlocks: item.recoveryBlocks,
});
const policy = toPolicy(input.policy);
const expected: PayoutExpectation = {
  recipients: input.recipients.map((r) => ({ address: r.address, amountSats: BigInt(r.amountSats) })),
  maxFeeSats: BigInt(input.maxFeeSats),
  feePaidBy: input.feePaidBy ?? "clan",
};
const refusal = (run: () => unknown) => {
  try {
    run();
    return null;
  } catch (error) {
    return (error as Error).message;
  }
};

if (input.sweep) {
  const move: SweepExpectation = {
    destination: toPolicy(input.sweep.destination),
    index: input.sweep.index,
    maxFeeSats: BigInt(input.maxFeeSats),
  };
  const checked = reviewSweep(input.psbt, policy, move);
  console.log(
    JSON.stringify({
      review: {
        feeSats: Number(checked.feeSats),
        amountSats: Number(checked.amountSats),
        address: checked.address,
        inputs: checked.inputs.length,
      },
      signed: input.words.map((words) => signSweep(input.psbt, words, policy, move)),
      refusals: {
        ...Object.fromEntries(
          Object.entries(input.tampered).map(([name, psbt]) => [name, refusal(() => reviewSweep(psbt, policy, move))]),
        ),
        lowFeeLimit: refusal(() => reviewSweep(input.psbt, policy, { ...move, maxFeeSats: checked.feeSats - 1n })),
        wrongIndex: refusal(() => reviewSweep(input.psbt, policy, { ...move, index: move.index + 1 })),
        // Checking a move with the new wallet's copy as the source: the coins aren't in it.
        wrongSource: refusal(() => reviewSweep(input.psbt, move.destination, move)),
        outsider: refusal(() => signSweep(input.psbt, "abandon ".repeat(11) + "about", policy, move)),
      },
    }),
  );
  process.exit(0);
}

const review = reviewPayout(input.psbt, policy, expected);
console.log(
  JSON.stringify({
    keys: input.words.map((words) => keyExpression(signerFromWords(words, policy.network).info)),
    unspendableKey: unspendableKey(policy),
    descriptors: { external: descriptor(policy, "external"), internal: descriptor(policy, "internal") },
    walletCode: walletCode(policy),
    addresses: [0, 1, 2].map((index) => clanOutput(policy, "external", index).address),
    changeAddresses: [0, 1].map((index) => clanOutput(policy, "internal", index).address),
    review: { feeSats: Number(review.feeSats), changeSats: Number(review.changeSats), inputs: review.inputs.length },
    signed: input.words.map((words) => signPayout(input.psbt, words, policy, expected)),
    refusals: {
      ...Object.fromEntries(
        Object.entries(input.tampered).map(([name, psbt]) => [name, refusal(() => reviewPayout(psbt, policy, expected))]),
      ),
      lowFeeLimit: refusal(() => reviewPayout(input.psbt, policy, { ...expected, maxFeeSats: review.feeSats - 1n })),
      wrongAmount: refusal(() =>
        reviewPayout(input.psbt, policy, {
          ...expected,
          recipients: expected.recipients.map((r) => ({ ...r, amountSats: r.amountSats + 1n })),
        }),
      ),
      outsider: refusal(() =>
        signPayout(input.psbt, "abandon ".repeat(11) + "about", policy, expected),
      ),
    },
  }),
);
