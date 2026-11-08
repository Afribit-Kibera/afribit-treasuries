import React from "react";
import ReactDOM from "react-dom/client";
// Bundled fonts, the same families as the phone app. Nothing loads from a CDN.
import "@fontsource-variable/manrope/wght.css";
import "@fontsource-variable/sora/wght.css";
import "@fontsource-variable/space-grotesk/wght.css";
import "@fontsource/cormorant-garamond/600.css";
import "@fontsource/cormorant-garamond/700.css";
import "./tokens.css";
import "./app.css";
import App from "./App";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
