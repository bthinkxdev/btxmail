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
const SHELL_URLS = self.__PRECACHE_URLS__ || ["/", "/offline.html", "/manifest.webmanifest", "/favicon.png", "/logo-mark.png"];

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

/* ------------------------------------------------------------------ Web Push */
const ICON = "/icons/icon-192.png";
const BADGE = "/icons/badge-96.png";
const MAX_LINES = 5;

self.addEventListener("push", (event) => event.waitUntil(showPush(event)));

async function showPush(event) {
  let d = {};
  try {
    d = event.data ? event.data.json() : {};
  } catch {
    d = { title: "BThinkX Mail", body: event.data ? event.data.text() : "" };
  }
  const kind = d.kind || "general";

  // Someone is already looking at the portal: let the page refresh itself instead of interrupting.
  if (kind !== "mail" && kind !== "test") {
    const open = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    const visible = open.filter((c) => c.visibilityState === "visible" && c.focused);
    if (visible.length) {
      visible.forEach((c) => c.postMessage({ type: "push", kind }));
      return;
    }
  }

  const tag = d.tag || kind;
  const footer = [d.account, d.center].filter(Boolean).join(" · ");
  let title = d.title || "BThinkX Mail";
  let body = [d.body, footer].filter(Boolean).join("\n");
  let data = { url: d.url || "/", kind, count: 1, items: [] };

  if (kind === "mail") {
    // Gmail-style grouping: one notification per mailbox that summarises everything unread.
    const previous = (await self.registration.getNotifications({ tag }))[0];
    const prior = previous && previous.data ? previous.data : { count: 0, items: [] };
    const items = [...prior.items, { sender: d.sender || d.title, subject: d.body }].slice(-MAX_LINES);
    const count = prior.count + 1;
    data = { url: d.url || "/", kind, count, items };
    if (count > 1) {
      title = count + " new messages";
      body = items
        .slice()
        .reverse()
        .map((i) => i.sender + ": " + i.subject)
        .join("\n");
      if (footer) body += "\n" + footer;
    }
  }

  await self.registration.showNotification(title, {
    body,
    icon: ICON,
    badge: BADGE,
    tag,
    renotify: true,
    timestamp: d.ts || Date.now(),
    lang: "en",
    requireInteraction: kind === "security",
    silent: false,
    data,
    actions: kind === "mail" ? [{ action: "open", title: "Open inbox" }] : [{ action: "open", title: "Open" }],
  });
  await updateBadge();
}

async function updateBadge() {
  if (!("setAppBadge" in self.navigator)) return;
  const shown = await self.registration.getNotifications();
  const unread = shown.reduce((n, x) => n + (x.data && x.data.kind === "mail" ? x.data.count : 0), 0);
  try {
    if (unread > 0) await self.navigator.setAppBadge(unread);
    else await self.navigator.clearAppBadge();
  } catch {
    /* badges are best effort */
  }
}

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(openTarget(event.notification.data || {}));
});

self.addEventListener("notificationclose", (event) => {
  event.waitUntil(updateBadge());
});

async function openTarget(data) {
  const target = new URL(data.url || "/", self.location.origin);
  if (target.origin === self.location.origin) {
    const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const client of windows) {
      if (new URL(client.url).origin === self.location.origin) {
        await client.focus();
        if ("navigate" in client && client.url !== target.href) await client.navigate(target.href).catch(() => undefined);
        await updateBadge();
        return;
      }
    }
  }
  await self.clients.openWindow(target.href);
  await updateBadge();
}

// The browser rotated or expired the subscription: tell open pages so they re-register.
self.addEventListener("pushsubscriptionchange", (event) => {
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((all) => {
      all.forEach((c) => c.postMessage({ type: "pushsubscriptionchange" }));
    })
  );
});
