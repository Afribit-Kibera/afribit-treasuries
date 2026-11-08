// Signatory keys are created and kept on the signatory's device. Only the public key leaves it.

import { HDKey } from "@scure/bip32";
import { generateMnemonic, mnemonicToSeedSync, validateMnemonic } from "@scure/bip39";
import { wordlist } from "@scure/bip39/wordlists/english.js";
import { ClanWalletError, networkRules, type ClanNetwork, type SignerKeyInfo } from "./policy.ts";

/** 12 new backup words (128 bits). Shown once to the signatory to write down. */
export function createBackupWords(): string {
  return generateMnemonic(wordlist, 128);
}

export type SignerAccount = { info: SignerKeyInfo; account: HDKey };

/** The signing key these words give on a network. Test networks share one key; mainnet has its own. */
export function signerFromWords(words: string, network: ClanNetwork): SignerAccount {
  const normalized = words.trim().toLowerCase().split(/\s+/).join(" ");
  if (!validateMnemonic(normalized, wordlist)) throw new ClanWalletError("These backup words are not valid");
  const { path, versions } = networkRules(network);
  const master = HDKey.fromMasterSeed(mnemonicToSeedSync(normalized), versions);
  const account = master.derive("m/" + path);
  return {
    info: {
      fingerprint: master.fingerprint.toString(16).padStart(8, "0"),
      path,
      xpub: account.publicExtendedKey,
    },
    account,
  };
}
