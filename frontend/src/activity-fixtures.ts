// Imported only from the development preview. Synthetic activity, shaped like the server's.
import type { ActivityDetail, ActivityItem } from "./live-api";
import { fixturePayout } from "./wallet-payout-fixture";

const id = (n: number) =>
  `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
/** This event id answers 404, to show the "not in your clan" state. */
export const missingActivityId = id(99);
const minutesAgo = (now: number, minutes: number) =>
  new Date(now - minutes * 60_000).toISOString();

export function activityDetailsFixture(now = Date.now()): ActivityDetail[] {
  const at = (minutes: number) => minutesAgo(now, minutes);
  return [
    {
      id: id(1),
      event: "grant_disbursed",
      actor: "Wanjiru Tailor",
      at: at(20),
      title: "Grant paid",
      category: "money",
      summary:
        "The grant payment of 40,000 sats confirmed on the network. The member received 39,120 sats after the network fee.",
      details: [{ label: "Received", value: "39,120 sats" }],
      links: { grant_id: "fixture-grant", txid: fixturePayout.txid },
    },
    {
      id: id(2),
      event: "payout_signed",
      actor: "Amina Organizer",
      at: at(90),
      title: "Signed a payment",
      category: "money",
      summary:
        "Amina Organizer checked the payment on their phone and signed it with their key.",
      details: [{ label: "Key fingerprint", value: "9c0b6c6d" }],
      links: { payout_id: fixturePayout.id, txid: fixturePayout.txid },
    },
    {
      id: id(3),
      event: "wallet_alarm_unapproved_spend",
      actor: "Amina Organizer",
      at: at(200),
      title: "Wallet alarm",
      category: "security",
      summary:
        "The clan wallet's watcher saw something unexpected and raised an alarm. The community's oversight has been told. Check the wallet alarms for what to do.",
      details: [],
      links: {},
    },
    {
      id: id(4),
      event: "wallet_confirmed",
      actor: "Juma Mechanic",
      at: at(600),
      title: "Compared the wallet code",
      category: "wallet",
      summary:
        "Juma Mechanic compared the wallet code on their phone with the other signatories and it matched. This proves everyone's phone sees the same wallet.",
      details: [{ label: "Wallet code", value: "8yq3 zv5k" }],
      links: {},
    },
    {
      id: id(5),
      event: "grant_requested",
      actor: "Wanjiru Tailor",
      at: at(1500),
      title: "Asked for a grant",
      category: "grants",
      summary:
        "Wanjiru Tailor asked the clan for a grant. Members vote on it next.",
      details: [{ label: "Amount", value: "40,000 sats" }],
      links: { grant_id: "fixture-grant" },
    },
    {
      id: id(6),
      event: "member_joined",
      actor: "Juma Mechanic",
      at: at(3000),
      title: "Joined the clan",
      category: "members",
      summary:
        "Juma Mechanic accepted the invitation and joined the clan as a signatory.",
      details: [],
      links: {},
    },
    {
      id: id(7),
      event: "account_recovery_requested",
      actor: "Juma Mechanic",
      at: at(3100),
      title: "Asked to recover an account",
      category: "account",
      summary: "Juma Mechanic asked for help getting back into their account.",
      details: [],
      links: {},
    },
    {
      id: id(8),
      event: "clan_created",
      actor: "Amina Organizer",
      at: at(3200),
      title: "Created the clan",
      category: "clan",
      summary: "Amina Organizer created the clan and became its organizer.",
      details: [],
      links: {},
    },
  ];
}

const amounts: Record<string, Record<string, unknown>> = {
  [id(1)]: { amount_msat: "40000000" },
  [id(5)]: { amount_sats: 40000 },
};

export function activityPageFixture(now = Date.now()): {
  items: ActivityItem[];
  next_cursor: string | null;
} {
  const items: ActivityItem[] = activityDetailsFixture(now).map(
    ({ details: _details, links: _links, ...item }) => ({
      ...item,
      data: amounts[item.id] || {},
    }),
  );
  // An item from an older server, without a title or category, and one the server can't find.
  items.push(
    {
      id: id(98),
      event: "invitation_created",
      actor: "Amina Organizer",
      at: minutesAgo(now, 3300),
      data: {},
    },
    {
      id: missingActivityId,
      event: "invitation_revoked",
      actor: "Amina Organizer",
      at: minutesAgo(now, 3400),
      title: "Cancelled an invitation",
      category: "members",
      summary: "Amina Organizer cancelled an unused invitation.",
      data: {},
    },
  );
  return { items, next_cursor: null };
}
