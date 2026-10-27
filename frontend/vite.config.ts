import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

const SHELL = [
  "/",
  "/offline.html",
  "/manifest.webmanifest",
  "/favicon.svg",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/icons/badge-96.png",
  "/icons/apple-touch-icon.png",
];

// Injects the list of hashed build files into public/sw.js so the whole app shell is
// available offline after the first visit, and versions the cache by build content.
function precacheManifest(): Plugin {
  let outDir = "dist";
  return {
    name: "btx-sw-precache",
    apply: "build",
    configResolved(config) {
      outDir = resolve(config.root, config.build.outDir);
    },
    writeBundle(_options, bundle) {
      const built = Object.keys(bundle)
        .filter((name) => name.startsWith("assets/") && !name.endsWith(".map"))
        .map((name) => `/${name}`)
        .sort();
      const urls = [...SHELL, ...built];
      const version = createHash("sha256").update(urls.join("\n")).digest("hex").slice(0, 12);
      const file = resolve(outDir, "sw.js");
      const source = readFileSync(file, "utf8")
        .replace("self.__PRECACHE_URLS__", JSON.stringify(urls))
        .replace("__SW_VERSION__", version);
      writeFileSync(file, source);
    },
  };
}

// In development the SPA proxies the API to Django so cookies stay same-origin.
export default defineConfig({
  plugins: [react(), precacheManifest()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: process.env.VITE_API_PROXY ?? "http://127.0.0.1:8000", changeOrigin: false },
    },
  },
  build: { sourcemap: false, outDir: "dist", assetsDir: "assets" },
});
