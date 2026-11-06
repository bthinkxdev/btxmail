/*
 * BThinkX Mail (webmail) service worker.
 *
 * Deliberately minimal: it makes the inbox installable and shows a branded page when the device is
 * offline. It NEVER caches mail, API responses or any page — only the offline page and its icon —
 * so nothing private is stored on the device by the worker. Everything else goes straight to the network.
 */
const CACHE = "btx-webmail-v1";
const OFFLINE_URL = "/bthinkx-offline.html";
const PRECACHE = [OFFLINE_URL, "/img/bthinkx/icon-192.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.addAll(PRECACHE.map((u) => new Request(u, { cache: "reload" }))))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith("btx-webmail-") && k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  // Only page navigations get a fallback; every other request is left to the browser (no caching).
  if (req.mode !== "navigate") return;
  event.respondWith(
    fetch(req).catch(async () => (await caches.match(OFFLINE_URL)) || Response.error()),
  );
});
