// Checks src/vault/store.ts outside a browser. Run by backend/tests/test_vault_store.py.
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import {
  forgetVault,
  openVault,
  saveVault,
  setVaultEnvironment,
  vaultProtection,
  VaultLockedError,
  type VaultBackend,
  type VaultRecord,
} from "../src/vault/store.ts";

const WORDS = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about";
const records = new Map<string, VaultRecord>();
const memory: VaultBackend = {
  async get(id) {
    const record = records.get(id);
    return record && structuredClone(record);
  },
  async put(record) {
    records.set(record.clanId, structuredClone(record));
  },
  async delete(id) {
    records.delete(id);
  },
};

// A passkey stand-in: the PRF output is an HMAC of the salt under the credential's own secret.
function fakePasskey(secret: string, id = "credential-1") {
  return {
    async derive(salt: Uint8Array, credentialId?: Uint8Array) {
      if (credentialId) assert.equal(Buffer.from(credentialId).toString(), id);
      return {
        secret: new Uint8Array(createHmac("sha256", secret).update(salt).digest()),
        credentialId: new Uint8Array(Buffer.from(id)),
      };
    },
  };
}

async function refused(promise: Promise<unknown>, pattern: RegExp) {
  await assert.rejects(promise, (error: unknown) => {
    assert.ok(error instanceof VaultLockedError, String(error));
    assert.match(error.message, pattern);
    return true;
  });
}

setVaultEnvironment({ backend: memory, passkey: fakePasskey("phone-secret") });
const results: string[] = [];

// PIN: saves, reopens and normalizes the words.
assert.equal(await vaultProtection("clan-a"), null);
await saveVault("clan-a", `  ${WORDS.toUpperCase()}  `, { kind: "pin", pin: "482913" });
assert.equal(await vaultProtection("clan-a"), "pin");
assert.equal(await openVault("clan-a", { kind: "pin", pin: "482913" }), WORDS);
results.push("pin round trip");

// The stored record never contains the words.
const stored = records.get("clan-a")!;
assert.ok(!Buffer.from(stored.data).toString("latin1").includes("abandon"));
assert.ok(!JSON.stringify(stored).includes("abandon"));
assert.ok(!JSON.stringify(stored).includes("482913"));
results.push("no plaintext");

// Bad input is refused.
await refused(saveVault("clan-a", "not real words", { kind: "pin", pin: "482913" }), /not valid/);
await refused(saveVault("clan-a", WORDS, { kind: "pin", pin: "1234" }), /6 to 12 digits/);
await refused(openVault("clan-a", { kind: "passkey" }), /PIN/);
await refused(openVault("missing", { kind: "pin", pin: "482913" }), /no signing key/);
results.push("bad input");

// Wrong PINs are refused, and slowed down after five.
for (let attempt = 1; attempt <= 4; attempt++) {
  await refused(openVault("clan-a", { kind: "pin", pin: "000000" }), /Wrong PIN/);
}
assert.equal(records.get("clan-a")!.lockedUntil, 0);
await refused(openVault("clan-a", { kind: "pin", pin: "000000" }), /Wrong PIN/);
assert.ok(records.get("clan-a")!.lockedUntil > Date.now());
await refused(openVault("clan-a", { kind: "pin", pin: "482913" }), /Too many wrong PINs/);
records.get("clan-a")!.lockedUntil = 0;
assert.equal(await openVault("clan-a", { kind: "pin", pin: "482913" }), WORDS);
assert.equal(records.get("clan-a")!.failures, 0);
results.push("pin lockout");

// A record copied to another clan, or with its protection relabelled, won't open.
records.set("clan-b", { ...structuredClone(stored), clanId: "clan-b", failures: 0, lockedUntil: 0 });
await refused(openVault("clan-b", { kind: "pin", pin: "482913" }), /Wrong PIN/);
const tampered = structuredClone(stored);
tampered.data[0] ^= 1;
records.set("clan-a", { ...tampered, failures: 0, lockedUntil: 0 });
await refused(openVault("clan-a", { kind: "pin", pin: "482913" }), /Wrong PIN/);
results.push("bound to clan and untampered");

// Passkey: opens with the same passkey, not with another one.
await saveVault("clan-p", WORDS, { kind: "passkey" });
assert.equal(await vaultProtection("clan-p"), "passkey");
assert.equal(await openVault("clan-p", { kind: "passkey" }), WORDS);
setVaultEnvironment({ passkey: fakePasskey("other-phone-secret") });
await refused(openVault("clan-p", { kind: "passkey" }), /doesn't unlock/);
setVaultEnvironment({ passkey: fakePasskey("phone-secret") });
results.push("passkey");

await forgetVault("clan-p");
assert.equal(await vaultProtection("clan-p"), null);
results.push("forget");

console.log(JSON.stringify({ ok: true, results }));
