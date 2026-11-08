// Imported only from the development preview. Synthetic test-network alarms.
import type { WalletAlarm, WalletStatus, WalletView } from "./wallet-api";
import { walletFixture } from "./wallet-fixtures";

export function alarmViewFixture(status: WalletStatus = "active"): WalletView {
  return { ...walletFixture(status), alarms_recent: 2 };
}
/** Newest first, dated relative to now so the 30-day checks keep working. */
export function alarmsFixture(now = Date.now()): WalletAlarm[] {
  const ago = (hours: number) =>
    new Date(now - hours * 60 * 60 * 1000).toISOString();
  return [
    {
      id: "fixture-alarm-spend",
      kind: "unapproved_spend",
      reference: "4f1c".padEnd(64, "0"),
      clan_id: "preview",
      generation: 1,
      created_at: ago(2),
      members: true,
      message:
        "Money left the clan wallet without an approved payout. Afribit is looking into it. Don't approve anything until Afribit has explained it.",
      detail: {},
    },
    {
      id: "fixture-alarm-code",
      kind: "wallet_code_mismatch",
      reference: "fixture-wallet",
      clan_id: "preview",
      generation: 1,
      created_at: ago(26),
      members: true,
      message:
        "A signatory's phone computed a different wallet code. Don't use this wallet until Afribit has checked it.",
      detail: { signer_id: "fixture-1", phone_code: "7Q2M-K9XD" },
    },
  ];
}
