import { checkedWallet, type CheckedWallet } from "./wallet-trust";
import {
  safeSats,
  toClanPolicy,
  type PayoutDraft,
  type WalletView,
} from "./wallet-api";
import {
  amountsReceived,
  reviewPayout,
  reviewSweep,
  type PayoutExpectation,
  type SweepExpectation,
} from "./vault/sign";

export function reviewWalletPayment(
  clanId: string,
  view: WalletView,
  draft: PayoutDraft,
) {
  if (
    draft.clan_id !== clanId ||
    !Number.isSafeInteger(draft.generation) ||
    draft.generation < 1
  )
    throw Error(
      "This payment does not match your clan wallet. Do not sign it.",
    );
  if (draft.kind !== "grant") return reviewWalletSweep(clanId, view, draft);
  const saved =
    view.me.is_signer || draft.generation !== view.generation
      ? checkedWallet(clanId, view, draft.generation)
      : null;
  const policy = toClanPolicy(saved?.policy || view.policy!);
  if (draft.fee_paid_by !== "recipients" || draft.destination !== null)
    throw Error("The payment is not using the agreed network fee rule.");
  const expected: PayoutExpectation = {
    recipients: draft.recipients.map((r) => ({
      address: r.address,
      amountSats: safeSats(r.approved_sats),
    })),
    maxFeeSats: safeSats(draft.max_fee_sats),
    feePaidBy: "recipients",
  };
  const review = reviewPayout(draft.psbt, policy, expected);
  if (review.feeSats !== safeSats(draft.fee_sats))
    throw Error("The displayed network fee does not match this payment.");
  const received = amountsReceived(
    expected.recipients,
    review.feeSats,
    expected.feePaidBy,
  );
  if (
    received.some(
      (r, i) => r.amountSats !== safeSats(draft.recipients[i].received_sats),
    )
  )
    throw Error(
      "The amount each member receives does not match this payment.",
    );
  return {
    kind: "grant" as const,
    policy,
    expected,
    review,
    received,
    sourceKey: saved?.key,
    snapshot: JSON.stringify(draft),
  };
}

const compareFirst = "Compare the new wallet's code on this phone first.";

// Refreshes and moves: both wallets come only from this phone's own saved checks.
// The server's destination address, amount and fee are never used.
function reviewWalletSweep(
  clanId: string,
  view: WalletView,
  draft: PayoutDraft,
) {
  const destination = draft.destination;
  if (
    !["move", "refresh"].includes(draft.kind) ||
    draft.fee_paid_by !== "clan" ||
    draft.recipients.length ||
    !destination ||
    destination.keychain !== "internal" ||
    !Number.isSafeInteger(destination.generation) ||
    !Number.isSafeInteger(destination.index) ||
    destination.index < 0 ||
    (draft.kind === "move"
      ? destination.generation <= draft.generation
      : destination.generation !== draft.generation)
  )
    throw Error(
      "This move does not match the clan's wallet rules. Do not sign it.",
    );
  let saved: CheckedWallet, receiving: CheckedWallet;
  try {
    saved = checkedWallet(clanId, view, draft.generation);
  } catch {
    throw Error(
      draft.kind === "move"
        ? "This phone has no check of the old wallet's code, so it cannot sign this move. The other signatories sign it."
        : compareFirst,
    );
  }
  try {
    receiving = checkedWallet(clanId, view, destination.generation);
  } catch {
    throw Error(compareFirst);
  }
  const policy = toClanPolicy(saved.policy);
  const expected: SweepExpectation = {
    destination: toClanPolicy(receiving.policy),
    index: destination.index,
    maxFeeSats: safeSats(draft.max_fee_sats),
  };
  const review = reviewSweep(draft.psbt, policy, expected);
  return {
    kind: "sweep" as const,
    policy,
    expected,
    review,
    sourceKey: saved.key,
    snapshot: JSON.stringify(draft),
  };
}
