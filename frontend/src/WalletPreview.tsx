// Development-only interaction harness. No real account, key store or payment provider.
import { useEffect, useState } from "react";
import { WalletCard } from "./WalletCard";
import { WalletPayout } from "./WalletPayout";
import { WalletDeposit } from "./WalletDeposit";
import type { WalletReceipt } from "./wallet-api";
import {
  addressFixture,
  nextWalletFixture,
  movedWalletFixture,
} from "./wallet-fixtures";
import { fixtureMove, fixtureRefresh } from "./wallet-sweep-fixture";
import { BeneficiaryAddress } from "./WalletGrantMoney";
import { Sheet } from "./ui";
import { DepositSheet, GrantMoney } from "./MoneyFlows";
import type { Grant } from "./live-api";
import { fixturePayout, tamperedPayout } from "./wallet-payout-fixture";
import { walletFixture, fixtureWords } from "./wallet-fixtures";
import { alarmsFixture } from "./wallet-alarm-fixtures";
import { ActivityScreen } from "./ActivityScreen";
import { ActivityDetailSheet, ActivityPaymentSheet } from "./ActivityDetail";
import type { ActivityItem } from "./live-api";
import {
  activityDetailsFixture,
  activityPageFixture,
} from "./activity-fixtures";
import { signerFromWords } from "./vault/keys";
import { keyExpression } from "./vault/policy";
import { vaultStore } from "./vault-access";
import { walletCode } from "./vault/policy";
import { toClanPolicy, type WalletStatus } from "./wallet-api";
let view = walletFixture("not_started");
let safety = "normal";
let depositCase = "normal";
let receipts: WalletReceipt[] = [];
let lastReceive = { purpose: "contribution", grant_id: null as string | null };
let payout: import("./wallet-api").PayoutDraft = JSON.parse(
  JSON.stringify(fixturePayout),
);
const grant = {
  id: "fixture-grant",
  amount_sats: 40000,
  accepted_at: "2026-11-04T09:00:00Z",
  status: "awaiting_signatures",
  outstanding_msat: "0",
} as Grant;
const originalFetch = window.fetch.bind(window);
window.fetch = async (input, init) => {
  const url =
    typeof input === "string"
      ? input
      : input instanceof Request
        ? input.url
        : input.toString();
  const path = new URL(url, location.origin).pathname;
  if (path === "/api/clans/preview/wallet/next") {
    view = nextWalletFixture();
    view.next!.start_reason = JSON.parse(String(init?.body)).reason;
    return Response.json(view);
  }
  if (path === "/api/clans/preview/wallet/next/cancel") {
    view = { ...view, next: null };
    return Response.json(view);
  }
  if (path === "/api/clans/preview/till")
    return Response.json({
      enabled: depositCase === "till",
      balance_sats: 0,
      cap_sats: 200000,
      sweep_at_sats: 100000,
      last_sweep: null,
    });
  if (path === "/api/clans/preview/wallet/address") {
    const params = new URL(url, location.origin).searchParams;
    lastReceive = {
      purpose: params.get("purpose") || "contribution",
      grant_id: params.get("grant_id"),
    };
    if (depositCase === "failure")
      return Response.json(
        { detail: "Connection lost. Try again." },
        { status: 503 },
      );
    return Response.json({
      ...addressFixture(),
      purpose: params.get("purpose"),
      grant_id: params.get("grant_id"),
      ...(depositCase === "tampered"
        ? { address: fixturePayout.recipients[0].address }
        : {}),
      ...(depositCase === "wrong-grant" ? { grant_id: "another-grant" } : {}),
    });
  }
  if (path === "/api/clans/preview/activity")
    return Response.json(activityPageFixture());
  const activityId = /^\/api\/clans\/preview\/activity\/([a-f0-9-]{36})$/.exec(
    path,
  )?.[1];
  if (activityId) {
    const found = activityDetailsFixture().find((d) => d.id === activityId);
    return found
      ? Response.json(found)
      : Response.json(
          { detail: "This activity isn't in your clan." },
          { status: 404 },
        );
  }
  if (path === "/api/clans/preview/wallet/alarms")
    return Response.json(view.alarms_recent ? alarmsFixture() : []);
  if (path === "/api/clans/preview/wallet/receipts")
    return Response.json(receipts);
  if (path === "/api/clans/preview/wallet/payouts") {
    const status = new URL(url, location.origin).searchParams.get("status");
    return Response.json(
      !status || status.split(",").includes(payout.status) ? [payout] : [],
    );
  }
  if (path === "/api/clans/preview/wallet/payouts/fixture-payout/signature") {
    payout = {
      ...payout,
      status: "awaiting_oversight",
      signatures: {
        count: 2,
        required: 2,
        signed_by_me: true,
        names: ["Juma", "Amina"],
      },
    };
    return Response.json(payout);
  }
  if (path === "/api/clans/preview/wallet/payouts/fixture-payout")
    return Response.json(payout);
  if (
    path === "/api/clans/preview/grants/fixture-grant/payout-address" ||
    path === "/api/clans/preview/grants/fixture-grant/payout-quote"
  ) {
    const address = init?.body
      ? JSON.parse(String(init.body)).address
      : new URL(url, location.origin).searchParams.get("address");
    return Response.json({
      address,
      approved_sats: 40000,
      fee_paid_by: "recipients",
      estimated_fee_sats: 454,
      estimated_received_sats: safety === "bad-estimate" ? 40000 : 39546,
      fee_rate_sat_vb: 2,
    });
  }
  if (path === "/api/rates/KES")
    return Response.json({
      currency: "KES",
      per_btc: "10000000",
      published_at: Math.floor(Date.now() / 1000),
      valid_until: Math.floor(Date.now() / 1000) + 300,
      source: "development fixture",
    });
  if (path === "/api/clans/preview/wallet/keys") {
    const body = JSON.parse(String(init?.body));
    if (view.next) {
      const next = movedWalletFixture();
      view = {
        ...view,
        next: {
          ...next,
          status: "confirming",
          me: { ...next.me, key: body.key, confirmed: false },
          started_by: view.next.started_by,
          start_reason: view.next.start_reason,
        },
      };
      return Response.json(view);
    }
    view = {
      ...view,
      status: "collecting_keys",
      me: { ...view.me, key: body.key },
      signers: view.signers.map((s, i) =>
        i === 0 ? { ...s, key_registered: true } : s,
      ),
    };
    return Response.json(view);
  }
  if (path === "/api/clans/preview/wallet/confirm") {
    const body = JSON.parse(String(init?.body));
    if (view.next) {
      view = movedWalletFixture();
      payout = JSON.parse(JSON.stringify(fixtureMove));
      return Response.json(view);
    }
    if (
      safety === "confirm-refused" ||
      !view.policy ||
      body.wallet_code !== walletCode(toClanPolicy(view.policy))
    )
      return Response.json(
        { detail: "Your phone computed a different wallet code." },
        { status: 409 },
      );
    view = {
      ...view,
      status: "active",
      me: { ...view.me, confirmed: true },
      signers: view.signers.map((s) => ({ ...s, confirmed: true })),
    };
    return Response.json(view);
  }
  if (path === "/api/clans/preview/wallet") return Response.json(view);
  if (
    ["fixture-move", "fixture-refresh"].some(
      (id) => path === `/api/clans/preview/wallet/payouts/${id}`,
    )
  )
    return Response.json(payout);
  if (
    ["fixture-move", "fixture-refresh"].some(
      (id) => path === `/api/clans/preview/wallet/payouts/${id}/signature`,
    )
  ) {
    payout = {
      ...payout,
      status: "awaiting_oversight",
      signatures: { ...payout.signatures, count: 2, signed_by_me: true },
    };
    return Response.json(payout);
  }
  return originalFetch(input, init);
};
export default function WalletPreview() {
  const [version, setVersion] = useState(0);
  const [screen, setScreen] = useState<
    | "payout"
    | "address"
    | "contribution"
    | "repayment"
    | "payment-routing"
    | "deposit-routing"
    | "activity"
    | null
  >(null);
  const [activityItem, setActivityItem] = useState<ActivityItem | null>(null);
  const [activityPayment, setActivityPayment] = useState<{
    id: string;
    grantId?: string;
  } | null>(null);
  useEffect(() => {
    document.documentElement.dataset.theme = "dark";
    const confirm = () => {
      receipts = [
        {
          id: "1".repeat(64) + ":0",
          txid: "1".repeat(64),
          vout: 0,
          address: addressFixture().address,
          purpose: lastReceive.purpose as WalletReceipt["purpose"],
          grant_id: lastReceive.grant_id,
          amount_sats: 10000,
          confirmations: 3,
          status: "confirmed",
        },
      ];
    };
    window.addEventListener("wallet-preview-confirm", confirm);
    return () => window.removeEventListener("wallet-preview-confirm", confirm);
  }, []);
  return (
    <div className="app live-app">
      <div className="background-art" />
      <div className="app-shell">
        <header className="app-header">
          <strong>Clan wallet · local preview</strong>
          <button
            className="text-button"
            onClick={() => {
              document.documentElement.dataset.theme =
                document.documentElement.dataset.theme === "dark"
                  ? "light"
                  : "dark";
            }}
          >
            Change theme
          </button>
        </header>
        <main className="content-page">
          <label>
            Wallet status
            <select
              aria-label="Wallet status"
              value={view.status}
              onChange={(e) => {
                const next = walletFixture(e.target.value as WalletStatus);
                if (next.policy && view.me.key) {
                  next.policy.signers = next.policy.signers
                    .filter((k) => k !== next.me.key)
                    .concat(view.me.key)
                    .sort();
                  next.me.key = view.me.key;
                  next.wallet_code = walletCode(toClanPolicy(next.policy));
                }
                view = next;
                setVersion((n) => n + 1);
              }}
            >
              {[
                "not_started",
                "collecting_keys",
                "confirming",
                "active",
                "retired",
              ].map((v) => (
                <option key={v}>{v}</option>
              ))}
            </select>
          </label>
          <button
            className="secondary-button"
            onClick={async () => {
              await (
                await vaultStore()
              ).saveVault("preview", fixtureWords(2), {
                kind: "pin",
                pin: "123456",
              });
              view = walletFixture("confirming");
              for (const key of Object.keys(localStorage))
                if (
                  key.startsWith("clans-public-wallet-check-") ||
                  key.startsWith("clans-public-wallet-recheck-")
                )
                  localStorage.removeItem(key);
              setVersion((n) => n + 1);
            }}
          >
            Use test signing key
          </button>
          <label>
            Safety case
            <select
              value={safety}
              onChange={(e) => {
                safety = e.target.value;
                view = walletFixture("confirming");
                if (safety === "server-code") view.wallet_code = "xxxxxxxx";
                if (safety === "missing-key")
                  view.me.key = keyExpression(
                    signerFromWords(fixtureWords(5), "signet").info,
                  );
                if (safety === "key-not-in-wallet")
                  view.policy!.signers = view
                    .policy!.signers.filter((k) => k !== view.me.key)
                    .concat(
                      keyExpression(signerFromWords(fixtureWords(5), "signet").info),
                    )
                    .sort();
                if (safety === "member") {
                  view.me.is_signer = false;
                  view.me.key = null;
                }
                if (safety === "disabled") view.enabled = false;
                if (safety === "alarms") view.alarms_recent = 2;
                setVersion((n) => n + 1);
              }}
            >
              <option value="normal">Normal</option>
              <option value="server-code">Server code differs</option>
              <option value="missing-key">Wrong phone key</option>
              <option value="key-not-in-wallet">
                Phone key missing from wallet
              </option>
              <option value="confirm-refused">Confirmation refused</option>
              <option value="member">Member only</option>
              <option value="disabled">Feature disabled</option>
              <option value="alarms">Wallet alarms</option>
            </select>
          </label>
          <WalletCard
            key={version}
            clanId="preview"
            clanName="Soweto Traders"
          />
          <button
            className="secondary-button"
            onClick={() => {
              view = nextWalletFixture();
              setVersion((n) => n + 1);
            }}
          >
            Show new wallet fixture
          </button>
          <button
            className="secondary-button"
            onClick={() => {
              view = movedWalletFixture();
              payout = JSON.parse(JSON.stringify(fixtureMove));
              setVersion((n) => n + 1);
            }}
          >
            Show moved wallet fixture
          </button>
          <button
            className="secondary-button"
            onClick={() => {
              view = walletFixture("active");
              payout = JSON.parse(JSON.stringify(fixtureRefresh));
              setVersion((n) => n + 1);
            }}
          >
            Show wallet refresh fixture
          </button>
          <label>
            Payout case
            <select
              aria-label="Payout case"
              onChange={(e) => {
                payout = JSON.parse(
                  JSON.stringify(
                    e.target.value === "tampered"
                      ? tamperedPayout
                      : fixturePayout,
                  ),
                );
                safety = e.target.value;
                if (
                  [
                    "awaiting_oversight",
                    "broadcasting",
                    "broadcast",
                    "confirmed",
                    "replaced",
                    "expired",
                  ].includes(safety)
                )
                  payout.status = safety as import("./wallet-api").PayoutStatus;
                if (safety === "bad-fee") payout.fee_sats = 1;
              }}
            >
              {[
                "normal",
                "tampered",
                "bad-fee",
                "bad-estimate",
                "awaiting_oversight",
                "broadcasting",
                "broadcast",
                "confirmed",
                "replaced",
                "expired",
              ].map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </label>
          <button
            className="secondary-button"
            onClick={() => setScreen("payout")}
          >
            Review test payout
          </button>
          <button
            className="secondary-button"
            onClick={() => setScreen("address")}
          >
            Add test receiving address
          </button>
          <button
            className="secondary-button"
            onClick={() => setScreen("payment-routing")}
          >
            Test grant routing
          </button>
          <button
            className="secondary-button"
            onClick={() => setScreen("deposit-routing")}
          >
            Test deposit routing
          </button>
          <button
            className="secondary-button"
            onClick={() => {
              view = walletFixture("active");
              payout = JSON.parse(JSON.stringify(fixturePayout));
              setScreen("activity");
            }}
          >
            Show test activity
          </button>
          {screen === "activity" && (
            <ActivityScreen
              clanId="preview"
              clanName="Soweto Traders"
              labels={{}}
              pending={null}
              onOpen={setActivityItem}
            />
          )}
          {activityItem && (
            <ActivityDetailSheet
              key={activityItem.id}
              clanId="preview"
              item={activityItem}
              labels={{}}
              network={view.network}
              canOpenGrant={(id) => id === grant.id}
              canOpenPayment={view.enabled}
              onOpenGrant={() => {
                setActivityItem(null);
                setScreen("payment-routing");
              }}
              onOpenPayment={(id, grantId) => {
                setActivityItem(null);
                setActivityPayment({ id, grantId });
              }}
              onClose={() => setActivityItem(null)}
            />
          )}
          {activityPayment && (
            <ActivityPaymentSheet
              key={activityPayment.id}
              clanId="preview"
              payoutId={activityPayment.id}
              grantId={activityPayment.grantId}
              view={view}
              beneficiaryOf={() => undefined}
              onCheckWallet={() => setActivityPayment(null)}
              onRefresh={async () => {}}
              onClose={() => setActivityPayment(null)}
            />
          )}
          {screen === "payment-routing" && (
            <Sheet
              title="Grant payment routing"
              onClose={() => setScreen(null)}
            >
              <GrantMoney
                clanId="preview"
                grant={grant}
                isBeneficiary
                payoutsEnabled
                receivingEnabled
                busy={false}
                run={async (fn) => {
                  await fn();
                }}
                onRefresh={async () => {}}
                onRepay={() => {}}
              />
            </Sheet>
          )}
          {screen === "deposit-routing" && (
            <DepositSheet
              clanId="preview"
              clanName="Soweto Traders"
              max={100000}
              busy={false}
              run={async (fn) => {
                await fn();
              }}
              onRefresh={async () => {}}
              onClose={() => setScreen(null)}
            />
          )}
          <label>
            Deposit case
            <select
              aria-label="Deposit case"
              onChange={(e) => {
                depositCase = e.target.value;
                receipts = [];
              }}
            >
              {["normal", "tampered", "wrong-grant", "failure", "till"].map(
                (v) => (
                  <option key={v}>{v}</option>
                ),
              )}
            </select>
          </label>
          <button
            className="secondary-button"
            onClick={() => {
              receipts = [];
              setScreen("contribution");
            }}
          >
            Test contribution
          </button>
          <button
            className="secondary-button"
            onClick={() => {
              receipts = [];
              setScreen("repayment");
            }}
          >
            Test repayment
          </button>
          {(screen === "contribution" || screen === "repayment") && (
            <WalletDeposit
              clanId="preview"
              clanName="Soweto Traders"
              grantId={screen === "repayment" ? "fixture-grant" : undefined}
              view={view}
              onClose={() => setScreen(null)}
              onLightning={() => {}}
            />
          )}
          {(screen === "payout" || screen === "address") && (
            <Sheet
              title={
                screen === "payout" ? "Review payout" : "Receive your grant"
              }
              onClose={() => setScreen(null)}
            >
              {screen === "payout" ? (
                <WalletPayout
                  clanId="preview"
                  grantId="fixture-grant"
                  view={view}
                />
              ) : (
                <BeneficiaryAddress clanId="preview" grant={grant} network="signet" />
              )}
            </Sheet>
          )}
        </main>
      </div>
    </div>
  );
}
