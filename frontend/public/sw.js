/* BThinkX Mail service worker.
 *
 * - Precaches the app shell (the list is injected at build time by vite.config.ts).
 * - Hashed /assets/* are cache-first; navigations are network-first with an offline page.
 * - /api/* and anything that is not a same-origin GET are NEVER handled or cached, so
 *   tenant data and session cookies never end up in Cache Storage.
 */
const VERSION = "__SW_VERSION__";
const PRECACHE = "btx-shell-" + VERSION;
const RUNTIME = "btx-runtime-v1";
const SHELL_URLS = self.__PRECACHE_URLS__ || ["/", "/offline.html", "/manifest.webmanifest", "/favicon.svg"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(PRECACHE)
      .then((cache) => cache.addAll(SHELL_URLS.map((u) => new Request(u, { cache: "reload" }))))
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keep = new Set([PRECACHE, RUNTIME]);
      for (const key of await caches.keys()) {
        if (key.startsWith("btx-") && !keep.has(key)) await caches.delete(key);
      }
      if (self.registration.navigationPreload) await self.registration.navigationPreload.enable();
      await self.clients.claim();
    })()
  );
});

self.addEventListener("message", (event) => {
  if (event.data === "SKIP_WAITING") self.skipWaiting();
  if (event.data === "CLEAR_CACHES") {
    event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k.startsWith("btx-runtime")).map((k) => caches.delete(k)))));
  }
});

const NEVER = [/^\/api\//, /^\/healthz/, /^\/readyz/, /^\/metrics/, /^\/django-admin\//, /^\/django-static\//, /^\/sw\.js$/];

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (NEVER.some((re) => re.test(url.pathname))) return;

  if (req.mode === "navigate") {
    event.respondWith(navigate(event));
    return;
  }
  if (url.pathname.startsWith("/assets/")) {
    event.respondWith(cacheFirst(req));
    return;
  }
  if (SHELL_URLS.includes(url.pathname) || url.pathname.startsWith("/icons/")) {
    event.respondWith(staleWhileRevalidate(req));
  }
});

async function navigate(event) {
  try {
    const preload = await event.preloadResponse;
    if (preload) return preload;
    return await fetch(event.request);
  } catch {
    const cache = await caches.open(PRECACHE);
    // Every SPA route is served by the same shell; it will show its own "offline" notice.
    return (await cache.match("/")) || (await cache.match("/offline.html")) || Response.error();
  }
}

async function cacheFirst(req) {
  const hit = await caches.match(req);
  if (hit) return hit;
  const res = await fetch(req);
  if (res.ok) (await caches.open(RUNTIME)).put(req, res.clone());
  return res;
}

async function staleWhileRevalidate(req) {
  const cache = await caches.open(PRECACHE);
  const hit = await cache.match(req);
  const refresh = fetch(req)
    .then((res) => {
      if (res.ok) cache.put(req, res.clone());
      return res;
    })
    .catch(() => hit);
  return hit || refresh;
}
