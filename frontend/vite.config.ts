import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

export default defineConfig({
  build: {
    manifest: true,
    rolldownOptions: {
      input: {
        app: fileURLToPath(new URL("./index.html", import.meta.url)),
        about: fileURLToPath(new URL("./about/index.html", import.meta.url)),
      },
    },
  },
  plugins: [react()],
  optimizeDeps: { include: ["@noble/hashes/scrypt.js"] },
  server: {
    host: "127.0.0.1",
    port: 5177,
    strictPort: true,
    proxy: {
      "/api": process.env.CLANS_DEV_API_TARGET || "http://127.0.0.1:8410",
    },
  },
  preview: { host: "127.0.0.1", port: 5177, strictPort: true },
});
