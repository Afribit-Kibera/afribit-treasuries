import React from "react";
import ReactDOM from "react-dom/client";
import App from "./LiveApp";
import { RegionProvider } from "./Region";
import "./styles.css";
import "./live.css";
import "./wallet.css";

const root = ReactDOM.createRoot(document.getElementById("root")!);
if (import.meta.env.DEV && location.pathname === "/__wallet_preview") {
  void import("./WalletPreview").then(({ default: Preview }) =>
    root.render(
      <RegionProvider>
        <Preview />
      </RegionProvider>,
    ),
  );
} else
  root.render(
    <React.StrictMode>
      <RegionProvider>
        <App />
      </RegionProvider>
    </React.StrictMode>,
  );

// Production shell only. Never cache API responses, tokens or payment actions.
if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}
