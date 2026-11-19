import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The dev server proxies /api to the local backend so the browser talks to a single origin.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: { "/api": { target: process.env.IOI_API_URL ?? "http://127.0.0.1:8000", changeOrigin: false } },
  },
  preview: { host: "127.0.0.1", port: 4173, proxy: { "/api": "http://127.0.0.1:8000" } },
});
