// Checks the F10 move and refresh fixtures with the phone's own review rules.
// Run: npm run check:sweeps (bundles this file for Node, then runs it).
import { reviewSweep, signSweep } from "../src/vault/sign.ts";
import { toClanPolicy, type PayoutDraft } from "../src/wallet-api";
import {
  fixtureWords,
  movedWalletFixture,
  nextWalletFixture,
  walletFixture,
} from "../src/wallet-fixtures";
import { fixtureMove, fixtureRefresh } from "../src/wallet-sweep-fixture";
import { checkedWallet, saveWalletCheck } from "../src/wallet-trust";
import { reviewWalletPayment } from "../src/wallet-review";

const store = new Map<string, string>();
(globalThis as { localStorage?: unknown }).localStorage = {
  getItem: (k: string) => store.get(k) ?? null,
  setItem: (k: string, v: string) => void store.set(k, String(v)),
  removeItem: (k: string) => void store.delete(k),
};

let passed = 0;
function check(name: string, ok: boolean) {
  if (!ok) throw Error("Failed: " + name);
  passed++;
}
function refused(name: string, run: () => unknown, message?: string) {
  try {
    run();
  } catch (e) {
    check(name, !message || (e as Error).message === message);
    return;
  }
  throw Error("Failed (accepted): " + name);
}
const copy = <T>(v: T): T => JSON.parse(JSON.stringify(v));
const compareFirst = "Compare the new wallet's code on this phone first.";

const old = walletFixture("active");
const moved = movedWalletFixture();
const oldPolicy = toClanPolicy(old.policy!);
const newPolicy = toClanPolicy(moved.policy!);
const move = fixtureMove as unknown as PayoutDraft;
const refresh = fixtureRefresh as unknown as PayoutDraft;

// The raw maths: the fixtures pass, and only for the phone's own destinations.
const m = reviewSweep(move.psbt, oldPolicy, {
  destination: newPolicy,
  index: 0,
  maxFeeSats: 10000n,
});
check("Move fixture passes reviewSweep", m.feeSats === BigInt(move.fee_sats));
check("Move pays the phone-derived address", m.address === move.destination!.address);
const r = reviewSweep(refresh.psbt, oldPolicy, {
  destination: oldPolicy,
  index: 4,
  maxFeeSats: 10000n,
});
check("Refresh fixture passes reviewSweep", r.amountSats > 0n);
refused("Move to the old wallet is refused", () =>
  reviewSweep(move.psbt, oldPolicy, { destination: oldPolicy, index: 0, maxFeeSats: 10000n }),
);
refused("Move beyond the first 1,000 change addresses is refused", () =>
  reviewSweep(move.psbt, oldPolicy, { destination: newPolicy, index: 1000, maxFeeSats: 10000n }),
);
refused("Refresh with a changed index is refused", () =>
  reviewSweep(refresh.psbt, oldPolicy, { destination: oldPolicy, index: 5, maxFeeSats: 10000n }),
);
refused("Fee above the limit is refused", () =>
  reviewSweep(move.psbt, oldPolicy, { destination: newPolicy, index: 0, maxFeeSats: 1n }),
);

// Wallet checks per generation. A v1 record reads as the generation it names.
const signerKey = old.me.key!;
store.set(
  "clans-public-wallet-check-v1:preview",
  JSON.stringify({ generation: 1, policy: old.policy, key: signerKey, code: old.wallet_code }),
);
check("v1 record reads as generation 1", checkedWallet("preview", old, 1).generation === 1);
refused("v1 record is not used for generation 2", () => checkedWallet("preview", moved, 2));

// Before the new wallet is checked on this phone, the move isn't signable.
refused(
  "Move without a check of the new wallet is refused",
  () => reviewWalletPayment("preview", moved, move),
  compareFirst,
);
// Check the new wallet as `next`, then after the switch.
const next = nextWalletFixture();
next.next = { ...moved, status: "confirming" } as typeof next.next;
saveWalletCheck("preview", { ...moved, status: "confirming" }, signerKey, moved.wallet_code!);
check("Next generation check is saved", checkedWallet("preview", next, 2).generation === 2);
check(
  "Old generation check survives a new one",
  store.has("clans-public-wallet-check-v1:preview") &&
    checkedWallet("preview", moved, 1).generation === 1,
);
check("Earlier generation needs the earlier code", checkedWallet("preview", moved, 1).code === old.wallet_code);
const badEarlier = copy(moved);
badEarlier.earlier[0].wallet_code = "xxxxxxxx";
refused("Earlier record with a different code is refused", () => checkedWallet("preview", badEarlier, 1));

const reviewed = reviewWalletPayment("preview", moved, move);
check(
  "Move reviews with the phone's saved wallets",
  reviewed.kind === "sweep" && reviewed.review.amountSats === m.amountSats,
);
check("Amount and fee come from the review", reviewed.review.feeSats === m.feeSats);
const otherAddress = copy(move);
otherAddress.destination!.address = refresh.destination!.address;
check(
  "Server address is never used",
  reviewWalletPayment("preview", moved, otherAddress).review.address === m.address,
);
const otherIndex = copy(move);
otherIndex.destination!.index = 1;
refused("Move with a changed index is refused", () => reviewWalletPayment("preview", moved, otherIndex));
const backwards = copy(move);
backwards.destination!.generation = 1;
refused("Move to a generation that isn't newer is refused", () =>
  reviewWalletPayment("preview", moved, backwards),
);
const otherGen = copy(refresh);
otherGen.destination!.generation = 2;
refused("Refresh to another generation is refused", () =>
  reviewWalletPayment("preview", moved, otherGen),
);
const unknownGen = copy(move);
unknownGen.destination!.generation = 3;
refused(
  "Move to an unchecked generation is refused",
  () => reviewWalletPayment("preview", moved, unknownGen),
  compareFirst,
);
const changedPolicy = copy(moved);
changedPolicy.policy!.recovery_blocks = 100;
refused("New wallet policy that differs from the check is refused", () =>
  reviewWalletPayment("preview", changedPolicy, move),
);
check(
  "Refresh of the old wallet reviews",
  reviewWalletPayment("preview", moved, refresh).kind === "sweep",
);
const signed = signSweep(move.psbt, fixtureWords(2), reviewed.policy, (reviewed as { expected: Parameters<typeof signSweep>[3] }).expected);
check("Move can be signed with an old-wallet key", signed !== move.psbt);
refused("A key outside the old wallet cannot sign the move", () =>
  signSweep(move.psbt, fixtureWords(5), reviewed.policy, (reviewed as { expected: Parameters<typeof signSweep>[3] }).expected),
);
console.log(JSON.stringify({ passed }));
