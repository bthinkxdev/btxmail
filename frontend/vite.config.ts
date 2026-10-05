import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the SPA proxies the API to Django so cookies stay same-origin.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: process.env.VITE_API_PROXY ?? "http://127.0.0.1:8000", changeOrigin: false },
    },
  },
  build: { sourcemap: false, outDir: "dist", assetsDir: "assets" },
});
