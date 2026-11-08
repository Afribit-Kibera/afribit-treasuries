import { useState } from "react";
import { DownloadSimple } from "@phosphor-icons/react";
import { Sheet } from "./ui";
import { type WalletView } from "./wallet-api";
import { walletMessage } from "./wallet-trust";
import {
  buildWalletBackup,
  rememberWalletBackup,
  walletBackupFilename,
  walletBackupSaved,
} from "./wallet-backup";
import { communityName } from "./community";

export function WalletBackup({
  clanId,
  clanName,
  view,
}: {
  clanId: string;
  clanName: string;
  view: WalletView;
}) {
  const [open, setOpen] = useState(false);
  const [downloaded, setDownloaded] = useState("");
  const [error, setError] = useState("");
  const [, setRevision] = useState(0);
  if (!view.enabled || view.status !== "active" || !view.me.is_signer)
    return null;
  let text: string;
  try {
    text = JSON.stringify(buildWalletBackup(clanId, view), null, 2) + "\n";
  } catch {
    return (
      <p className="fine-print">
        Compare the wallet code on this phone, then save a wallet backup. Your
        backup words alone are not enough to recover the clan wallet.
      </p>
    );
  }
  const saved = walletBackupSaved(clanId, text);
  function download() {
    setError("");
    setDownloaded("");
    let url = "";
    const link = document.createElement("a");
    try {
      // Recheck at the moment of export; never fetch a backup from the server.
      const current =
        JSON.stringify(buildWalletBackup(clanId, view), null, 2) + "\n";
      if (current !== text)
        throw Error(
          "The wallet changed. Close this screen and compare its code again.",
        );
      url = URL.createObjectURL(
        new Blob([current], { type: "application/json;charset=utf-8" }),
      );
      link.href = url;
      link.download = walletBackupFilename(clanName);
      document.body.append(link);
      link.click();
      setDownloaded(current);
    } catch (e) {
      setError(walletMessage(e));
    } finally {
      link.remove();
      // Give mobile browsers time to start reading the download.
      if (url) setTimeout(() => URL.revokeObjectURL(url), 60000);
    }
  }
  return (
    <>
      <p className="fine-print" role="status">
        {saved
          ? "Wallet backup saved on this phone. Keep a second copy somewhere else."
          : "Save your wallet backup. Your backup words alone are not enough to recover the clan wallet."}
      </p>
      <button
        className="secondary-button"
        onClick={() => {
          setError("");
          setDownloaded("");
          setOpen(true);
        }}
      >
        <DownloadSimple size={20} /> Save wallet backup
      </button>
      {open && (
        <Sheet
          title="Save wallet backup"
          eyebrow="Keep a second copy"
          onClose={() => setOpen(false)}
        >
          <div className="wallet-flow">
            <p>
              This file holds no secrets. Keep it with your backup words, and
              keep a second copy somewhere else.
            </p>
            <p>
              Together with enough signatories' words, it can recover the clan's
              money if Clans or {communityName()} is ever unavailable.
            </p>
            <p className="fine-print">
              The recovery wait still applies to each payment into the wallet.
              This file does not include your signing key or backup words.
            </p>
            <button className="primary-button" onClick={download}>
              <DownloadSimple size={22} /> Download backup file
            </button>
            {downloaded === text && (
              <>
                <p role="status">
                  Check your Downloads or Files app for{" "}
                  {walletBackupFilename(clanName)}. Only continue once you have
                  saved it.
                </p>
                <button
                  className="secondary-button"
                  onClick={() => {
                    try {
                      const current =
                        JSON.stringify(
                          buildWalletBackup(clanId, view),
                          null,
                          2,
                        ) + "\n";
                      if (current !== downloaded)
                        throw Error(
                          "The wallet changed. Download its backup again.",
                        );
                      rememberWalletBackup(clanId, current);
                      setRevision((n) => n + 1);
                      setOpen(false);
                    } catch (e) {
                      setError(walletMessage(e));
                    }
                  }}
                >
                  I've saved the file
                </button>
              </>
            )}
            {error && <p role="alert">{error}</p>}
          </div>
        </Sheet>
      )}
    </>
  );
}
