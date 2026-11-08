import { useEffect, useState } from "react";
import { Busy, Sheet } from "./ui";
import { WalletPayout } from "./WalletPayout";
import { getPayouts, type PayoutDraft, type WalletView } from "./wallet-api";
import { walletMessage } from "./wallet-trust";
export function WalletMaintenance({
  clanId,
  view,
  onRefresh,
}: {
  clanId: string;
  view: WalletView;
  onRefresh: () => Promise<unknown>;
}) {
  const [items, setItems] = useState<PayoutDraft[]>([]),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(true),
    [reload, setReload] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    let running = false;
    async function load() {
      if (running) return;
      running = true;
      try {
        const result = await getPayouts(clanId, {
          status: [
            "awaiting_signatures",
            "awaiting_oversight",
            "broadcasting",
            "broadcast",
          ],
        });
        if (result.some((item) => item.clan_id !== clanId))
          throw Error("These payments do not match your clan. Try again.");
        if (active) {
          setItems(
            result.filter(
              (item) => item.kind === "move" || item.kind === "refresh",
            ),
          );
          setError("");
        }
      } catch (e) {
        if (active) setError(walletMessage(e));
      } finally {
        running = false;
        if (active) setLoading(false);
      }
    }
    setLoading(true);
    void load();
    const timer = setInterval(() => void load(), 30000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [clanId, reload, view.generation]);
  return (
    <section className="wallet-flow" aria-label="Wallet moves and refreshes">
      {loading && <Busy busy>Checking wallet moves</Busy>}
      {error && (
        <>
          <p role="alert">{error}</p>
          <button
            className="secondary-button"
            onClick={() => setReload((n) => n + 1)}
          >
            Try wallet moves again
          </button>
        </>
      )}
      {items.map((item) => (
        <button
          className="secondary-button"
          key={item.id}
          onClick={() => setSelected(item.id)}
        >
          {item.kind === "move"
            ? "Review wallet move"
            : "Review wallet refresh"}{" "}
          · generation {item.generation}
        </button>
      ))}
      {selected && (
        <Sheet
          title="Clan wallet payment"
          onClose={() => {
            setSelected(null);
            setReload((n) => n + 1);
          }}
        >
          <WalletPayout
            key={selected}
            clanId={clanId}
            payoutId={selected}
            view={view}
            onRefresh={onRefresh}
          />
        </Sheet>
      )}
    </section>
  );
}
