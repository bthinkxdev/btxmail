/*
 * BThinkX Mail (webmail) service worker.
 *
 * - Makes the inbox installable and shows a branded page when the device is offline.
 * - Shows new-mail push notifications (sender, subject and the first words of the message).
 *
 * It NEVER caches mail, API responses or any page — only the offline page and its icon — so nothing private is
 * stored on the device by the worker. Everything else goes straight to the network.
 */
const CACHE = "btx-webmail-v2";
const OFFLINE_URL = "/bthinkx-offline.html";
const ICON = "/img/bthinkx/icon-192.png";
const BADGE = "/img/bthinkx/badge-96.png";
const INBOX = "/SOGo/";
const PRECACHE = [OFFLINE_URL, ICON];
const MAX_LINES = 5;

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

/* ------------------------------------------------------------------ Web Push */
self.addEventListener("push", (event) => event.waitUntil(showMail(event)));

async function showMail(event) {
  let d = {};
  try {
    d = event.data ? event.data.json() : {};
  } catch (e) {
    d = { title: "BThinkX Mail", body: event.data ? event.data.text() : "" };
  }
  const tag = d.tag || "mail";
  const sender = d.sender || d.title || "New message";
  const subject = d.body || "(no subject)";
  const preview = d.preview || "";

  // Gmail-style grouping: one notification per mailbox that summarises everything unread.
  const previous = (await self.registration.getNotifications({ tag }))[0];
  const prior = previous && previous.data ? previous.data : { count: 0, items: [] };
  const items = prior.items.concat([{ sender: sender, subject: subject }]).slice(-MAX_LINES);
  const count = prior.count + 1;

  let title = sender;
  let body = preview ? subject + "\n" + preview : subject;
  if (count > 1) {
    title = count + " new messages";
    body = items
      .slice()
      .reverse()
      .map((i) => i.sender + ": " + i.subject)
      .join("\n");
  }
  if (d.account) body += "\n" + d.account;

  await self.registration.showNotification(title, {
    body: body,
    icon: ICON,
    badge: BADGE,
    tag: tag,
    renotify: true,
    timestamp: d.ts || Date.now(),
    lang: "en",
    silent: false,
    data: { url: d.url || INBOX, count: count, items: items },
    actions: [{ action: "open", title: "Open inbox" }],
  });
  await updateBadge();
}

async function updateBadge() {
  if (!("setAppBadge" in self.navigator)) return;
  const shown = await self.registration.getNotifications();
  const unread = shown.reduce((n, x) => n + (x.data && x.data.count ? x.data.count : 0), 0);
  try {
    if (unread > 0) await self.navigator.setAppBadge(unread);
    else await self.navigator.clearAppBadge();
  } catch (e) {
    /* badges are best effort */
  }
}

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(openTarget(event.notification.data || {}));
});

self.addEventListener("notificationclose", (event) => event.waitUntil(updateBadge()));

async function openTarget(data) {
  const target = new URL(data.url || INBOX, self.location.origin);
  if (target.origin === self.location.origin) {
    const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const client of windows) {
      if (new URL(client.url).origin === self.location.origin) {
        await client.focus();
        await updateBadge();
        return;
      }
    }
  }
  await self.clients.openWindow(target.href);
  await updateBadge();
}

// The browser rotated or expired the subscription: register the new one with the portal (needs the signed-in session).
self.addEventListener("pushsubscriptionchange", (event) => {
  event.waitUntil(
    (async () => {
      try {
        const options = (event.oldSubscription && event.oldSubscription.options) || null;
        if (!options) return;
        const sub = await self.registration.pushManager.subscribe(options);
        await fetch("/bthinkx-push.php", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json", "X-Requested-With": "BThinkXMail" },
          body: JSON.stringify({ action: "subscribe", subscription: sub.toJSON() }),
        });
      } catch (e) {
        /* the next time the inbox is opened it re-registers */
      }
    })(),
  );
});
