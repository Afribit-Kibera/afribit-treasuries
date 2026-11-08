import React from "react";
import ReactDOM from "react-dom/client";
import ProductPage from "./ProductPage";
import "./styles.css";
import "./product.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ProductPage />
  </React.StrictMode>,
);
