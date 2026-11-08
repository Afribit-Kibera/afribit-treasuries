import { useEffect, useState } from "react";
import {
  DownloadSimple,
  ShareNetwork,
  PlusSquare,
} from "@phosphor-icons/react";
import { Sheet } from "./ui";

interface InstallPrompt extends Event {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}
let prompt: InstallPrompt | null = null;
const listeners = new Set<() => void>();
window.addEventListener("beforeinstallprompt", (event) => {
  event.preventDefault();
  prompt = event as InstallPrompt;
  listeners.forEach((notify) => notify());
});
window.addEventListener("appinstalled", () => {
  prompt = null;
  listeners.forEach((notify) => notify());
});
function installed() {
  return (
    window.matchMedia("(display-mode: standalone)").matches ||
    (navigator as Navigator & { standalone?: boolean }).standalone === true
  );
}

export function InstallControl() {
  const [isInstalled, setInstalled] = useState(installed);
  const [, render] = useState(0);
  const [guide, setGuide] = useState(false);
  const [opening, setOpening] = useState(false);
  const ios =
    /iPhone|iPad|iPod/.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  useEffect(() => {
    const media = window.matchMedia("(display-mode: standalone)");
    const update = () => {
      setInstalled(installed());
      render((n) => n + 1);
    };
    const appInstalled = () => {
      setInstalled(true);
      setGuide(false);
    };
    listeners.add(update);
    media.addEventListener("change", update);
    window.addEventListener("appinstalled", appInstalled);
    return () => {
      listeners.delete(update);
      media.removeEventListener("change", update);
      window.removeEventListener("appinstalled", appInstalled);
    };
  }, []);
  async function install() {
    if (!prompt) {
      setGuide(true);
      return;
    }
    const current = prompt;
    setOpening(true);
    try {
      await current.prompt();
      const choice = await current.userChoice;
      if (choice.outcome === "accepted") setGuide(false);
    } catch {
      setGuide(true);
    } finally {
      if (prompt === current) prompt = null;
      setOpening(false);
    }
  }
  if (isInstalled)
    return (
      <p className="field-help" role="status">
        Clans is already installed on this device.
      </p>
    );
  return (
    <>
      <button
        className="secondary-button install-button"
        disabled={opening}
        onClick={() => void install()}
      >
        <DownloadSimple size={21} />
        Install Clans
      </button>
      {guide && (
        <Sheet title="Add Clans to your phone" onClose={() => setGuide(false)}>
          <p>Open Clans from your home screen, like any other app.</p>
          <ol className="install-steps">
            {ios ? (
              <>
                <li>Open this page in Safari.</li>
                <li>
                  <ShareNetwork size={20} />
                  Tap Share.
                </li>
                <li>
                  <PlusSquare size={20} />
                  Choose <strong>Add to Home Screen</strong>, then{" "}
                  <strong>Add</strong>.
                </li>
              </>
            ) : (
              <>
                <li>Open your browser menu.</li>
                <li>
                  Choose <strong>Install app</strong> or{" "}
                  <strong>Add to Home screen</strong>.
                </li>
                <li>
                  Tap <strong>Install</strong> or <strong>Add</strong>.
                </li>
              </>
            )}
          </ol>
          <p className="fine-print">
            You can also keep using Clans in your browser. Installing does not
            give Clans access to your contacts, location, camera or microphone.
          </p>
        </Sheet>
      )}
    </>
  );
}
