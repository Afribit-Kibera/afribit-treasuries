// Public wallet rules only. No private key, backup word or PIN may enter this record.
import { signerFromWords } from "./vault/keys";
import { keyExpression, validatePolicy, walletCode, type ClanNetwork } from "./vault/policy";
import { toClanPolicy, type WalletPolicy, type WalletView } from "./wallet-api";
import { communityName } from "./community";
export type CheckedWallet = {
  generation: number;
  code: string;
  key: string;
  policy: WalletPolicy;
};
const storageKey = (id: string) => `clans-public-wallet-check-v1:${id}`;
const generationKey = (id: string, generation: number) =>
  `clans-public-wallet-check-v2:${id}:${generation}`;
const recheckKey = (id: string, generation: number) =>
  `clans-public-wallet-recheck-v1:${id}:${generation}`;
export function publicSigningKey(words: string, network: ClanNetwork) {
  const signer = signerFromWords(words, network);
  try {
    return keyExpression(signer.info);
  } finally {
    signer.account.wipePrivateData();
  }
}
export function ownWalletKey(words: string, view: WalletView) {
  if (!view.policy || !view.me.key)
    throw Error(
      `Your signing key is missing from this wallet. Stop and contact ${communityName()}.`,
    );
  const signer = signerFromWords(words, view.policy.network);
  try {
    const key = keyExpression(signer.info);
    if (key !== view.me.key || !view.policy.signers.includes(key))
      throw Error(
        `This phone’s signing key does not match the clan wallet. Do not use it. Contact ${communityName()}.`,
      );
    return key;
  } finally {
    signer.account.wipePrivateData();
  }
}
export function saveWalletCheck(
  id: string,
  view: WalletView,
  key: string,
  code: string,
) {
  if (
    view.generation === null ||
    !view.policy ||
    walletCode(toClanPolicy(view.policy)) !== code ||
    !view.policy.signers.includes(key)
  )
    throw Error("The wallet changed. Stop and compare its code again.");
  const record: CheckedWallet = {
    generation: view.generation,
    policy: view.policy,
    key,
    code,
  };
  try {
    localStorage.setItem(
      generationKey(id, record.generation),
      JSON.stringify(record),
    );
    localStorage.removeItem(recheckKey(id, record.generation));
  } catch {
    throw Error(
      "This phone cannot save the wallet check. Allow device storage and compare the code again.",
    );
  }
}
export function checkedWallet(
  id: string,
  view: WalletView,
  generation = view.generation,
): CheckedWallet {
  if (!Number.isSafeInteger(generation) || generation! < 1)
    throw Error("Compare the wallet code on this phone first.");
  let record: CheckedWallet | null = null;
  try {
    if (localStorage.getItem(recheckKey(id, generation!)))
      throw Error("Compare again");
    record = JSON.parse(
      localStorage.getItem(generationKey(id, generation!)) ||
        localStorage.getItem(storageKey(id)) ||
        "null",
    );
  } catch {
    /* Treat unreadable public state as unchecked. */
  }
  const current =
    view.generation === generation
      ? view
      : view.next?.generation === generation
        ? view.next
        : null;
  const earlier = view.earlier?.find((item) => item.generation === generation);
  if (record) validatePolicy(toClanPolicy(record.policy));
  if (
    !record ||
    record.generation !== generation ||
    !record.policy.signers.includes(record.key) ||
    walletCode(toClanPolicy(record.policy)) !== record.code ||
    (current
      ? !current.policy ||
        current.me.key !== record.key ||
        JSON.stringify(toClanPolicy(current.policy)) !==
          JSON.stringify(toClanPolicy(record.policy))
      : !earlier || earlier.wallet_code !== record.code)
  )
    throw Error(
      `Compare the wallet code on this phone before using the clan wallet. If it changed, stop and contact ${communityName()}.`,
    );
  return record;
}
// Retain all public records; restoring a key requires a fresh comparison for this generation.
export function requireWalletRecheck(id: string, generation: number | null) {
  if (generation !== null)
    localStorage.setItem(recheckKey(id, generation), "1");
}
export function walletMessage(error: unknown) {
  return (error instanceof Error ? error.message : "Please try again.")
    .replace(/PSBT/gi, "payment data")
    .replace(/descriptor/gi, "wallet rule")
    .replace(/xpub/gi, "public signing key")
    .replace(/UTXO/gi, "wallet funds");
}
