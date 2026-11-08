// Public recovery details only. Build from the rules compared on this phone.
import { checkedWallet } from "./wallet-trust";
import { toClanPolicy, type WalletView } from "./wallet-api";
import {
  descriptor,
  descriptorChecksum,
  keyExpression,
  threshold,
  validatePolicy,
  walletCode,
} from "./vault/policy";

export function buildWalletBackup(clanId: string, view: WalletView) {
  if (
    !view.enabled ||
    view.status !== "active" ||
    !view.me.is_signer ||
    !view.me.confirmed ||
    !Number.isSafeInteger(view.generation) ||
    view.generation! < 1
  )
    throw Error("Your clan wallet must be ready before you save its backup.");
  const checked = checkedWallet(clanId, view);
  const policy = toClanPolicy(checked.policy);
  validatePolicy(policy);
  const withChecksum = (chain: "external" | "internal") => {
    const text = descriptor(policy, chain);
    return `${text}#${descriptorChecksum(text)}`;
  };
  return {
    format: "afribit-clan-wallet-backup/1",
    network: policy.network,
    clan_id: clanId,
    generation: checked.generation,
    wallet_code: walletCode(policy),
    oversight: policy.oversight.map(keyExpression),
    signers: policy.signers.map(keyExpression),
    threshold: threshold(policy),
    recovery_threshold: policy.recoveryThreshold,
    recovery_blocks: policy.recoveryBlocks,
    descriptors: {
      external: withChecksum("external"),
      internal: withChecksum("internal"),
    },
  };
}

export function walletBackupFilename(clanName: string) {
  const name = clanName
    .normalize("NFC")
    .replace(/[<>:"/\\|?*\u0000-\u001f]/g, "-")
    .slice(0, 80)
    .replace(/^[\s.]+|[\s.]+$/g, "");
  return `${name || "Clan"}-wallet-backup.json`;
}

const receiptKey = (clanId: string) =>
  `clans-public-wallet-backup-v1:${clanId}`;
export function walletBackupSaved(clanId: string, text: string) {
  try {
    return localStorage.getItem(receiptKey(clanId)) === text;
  } catch {
    return false;
  }
}
export function rememberWalletBackup(clanId: string, text: string) {
  try {
    // Remember the exact public wallet, so a new generation needs a new backup.
    localStorage.setItem(receiptKey(clanId), text);
  } catch {
    throw Error(
      "This phone cannot remember that you saved the file. Keep your downloaded copy, allow device storage, then try again.",
    );
  }
}
