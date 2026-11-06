// >>> BThinkX PWA (managed by deploy/mailcow/webmail-pwa/install.sh — do not edit between the markers)
(function () {
  "use strict";
  var head = document.head || document.getElementsByTagName("head")[0];
  function add(tag, attrs) {
    var el = document.createElement(tag);
    for (var k in attrs) el.setAttribute(k, attrs[k]);
    head.appendChild(el);
    return el;
  }
  if (!document.querySelector('link[rel="manifest"]')) {
    add("link", { rel: "manifest", href: "/bthinkx-manifest.json" });
    add("link", { rel: "apple-touch-icon", href: "/img/bthinkx/apple-touch-icon.png" });
    add("link", { rel: "icon", type: "image/png", sizes: "32x32", href: "/img/bthinkx/favicon-32.png" });
    add("meta", { name: "mobile-web-app-capable", content: "yes" });
    add("meta", { name: "apple-mobile-web-app-capable", content: "yes" });
    add("meta", { name: "apple-mobile-web-app-title", content: "BThinkX Mail" });
    add("meta", { name: "application-name", content: "BThinkX Mail" });
  }
  var theme = document.querySelector('meta[name="theme-color"]') || add("meta", { name: "theme-color", content: "#000000" });
  // Match the browser/title bar to the app's own toolbar once the page has rendered.
  function syncTheme() {
    try {
      var bar = document.querySelector("md-toolbar, .md-toolbar-tools");
      var color = bar && getComputedStyle(bar).backgroundColor;
      if (color && color !== "rgba(0, 0, 0, 0)" && color !== "transparent") theme.setAttribute("content", color);
    } catch (e) { /* cosmetic only */ }
  }
  window.addEventListener("load", function () { setTimeout(syncTheme, 1500); });

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/bthinkx-sw.js", { scope: "/" }).catch(function () { /* not installable here */ });
    });
  }

  // "Install app" chip (Chrome/Edge/Android). Remembers a dismissal on this device.
  var deferred = null;
  var KEY = "btxInstallDismissed";
  function dismissed() { try { return sessionStorage.getItem(KEY) === "1"; } catch (e) { return false; } }
  function standalone() {
    return (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) || window.navigator.standalone === true;
  }
  window.addEventListener("beforeinstallprompt", function (e) {
    e.preventDefault();
    deferred = e;
    if (dismissed() || standalone() || document.getElementById("btx-install")) return;
    var box = document.createElement("div");
    box.id = "btx-install";
    box.setAttribute("role", "region");
    box.setAttribute("aria-label", "Install BThinkX Mail");
    box.style.cssText = "position:fixed;left:16px;bottom:16px;z-index:99999;display:flex;gap:10px;align-items:center;" +
      "background:#000;color:#fff;padding:10px 12px 10px 14px;border-radius:12px;font:600 14px system-ui,sans-serif;" +
      "box-shadow:0 6px 24px rgba(0,0,0,.35)";
    var label = document.createElement("span");
    label.textContent = "Install BThinkX Mail";
    var go = document.createElement("button");
    go.type = "button";
    go.textContent = "Install";
    go.style.cssText = "background:#fff;color:#000;border:0;border-radius:8px;padding:8px 14px;font:700 13px system-ui,sans-serif;cursor:pointer;min-height:36px";
    var no = document.createElement("button");
    no.type = "button";
    no.setAttribute("aria-label", "Dismiss");
    no.textContent = "✕";
    no.style.cssText = "background:transparent;color:#fff;border:0;font-size:16px;cursor:pointer;min-width:32px;min-height:36px";
    go.onclick = function () {
      box.remove();
      if (!deferred) return;
      deferred.prompt();
      deferred.userChoice.then(function () { deferred = null; });
    };
    no.onclick = function () {
      box.remove();
      try { sessionStorage.setItem(KEY, "1"); } catch (e2) { /* ignore */ }
    };
    box.appendChild(label);
    box.appendChild(go);
    box.appendChild(no);
    document.body.appendChild(box);
  });
  window.addEventListener("appinstalled", function () {
    var b = document.getElementById("btx-install");
    if (b) b.remove();
  });
})();

// New-mail push notifications (sender, subject, first words of the message) for this mailbox.
(function () {
  "use strict";
  var API = "/bthinkx-push.php";
  var DISMISS_KEY = "btxPushDismissedAt";
  var SYNC_KEY = "btxPushSyncedAt";
  var DAY = 24 * 60 * 60 * 1000;
  var POST_HEADERS = { "Content-Type": "application/json", "X-Requested-With": "BThinkXMail" };

  function read(key) { try { return Number(localStorage.getItem(key)) || 0; } catch (e) { return 0; } }
  function write(key) { try { localStorage.setItem(key, String(Date.now())); } catch (e) { /* ignore */ } }
  function dismissedNow() { try { return sessionStorage.getItem(DISMISS_KEY) === "1"; } catch (e) { return false; } }
  function dismissNow() { try { sessionStorage.setItem(DISMISS_KEY, "1"); } catch (e) { /* ignore */ } }
  function standalone() {
    return (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) || window.navigator.standalone === true;
  }
  function chipCss(bottom) {
    return "position:fixed;left:16px;bottom:" + bottom + "px;z-index:99998;display:flex;gap:10px;align-items:center;max-width:calc(100vw - 32px);" +
      "background:#000;color:#fff;padding:10px 12px 10px 14px;border-radius:12px;font:600 14px system-ui,sans-serif;" +
      "box-shadow:0 6px 24px rgba(0,0,0,.35)";
  }
  function button(label, primary) {
    var b = document.createElement("button");
    b.type = "button";
    b.textContent = label;
    b.style.cssText = primary
      ? "background:#fff;color:#000;border:0;border-radius:8px;padding:8px 14px;font:700 13px system-ui,sans-serif;cursor:pointer;min-height:36px"
      : "background:transparent;color:#fff;border:0;font-size:16px;cursor:pointer;min-width:32px;min-height:36px";
    return b;
  }
  function toast(text) {
    var t = document.createElement("div");
    t.setAttribute("role", "status");
    t.textContent = text;
    t.style.cssText = chipCss(16);
    document.body.appendChild(t);
    setTimeout(function () { t.remove(); }, 5000);
  }
  function urlBase64ToUint8Array(s) {
    var pad = "=".repeat((4 - (s.length % 4)) % 4);
    var raw = atob((s + pad).replace(/-/g, "+").replace(/_/g, "/"));
    var out = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out;
  }
  function post(body) {
    return fetch(API, { method: "POST", credentials: "same-origin", headers: POST_HEADERS, body: JSON.stringify(body) });
  }

  async function subscribe(cfg, reg) {
    var sub = await reg.pushManager.getSubscription();
    var key = urlBase64ToUint8Array(cfg.public_key);
    if (sub) {
      var current = sub.options && sub.options.applicationServerKey ? new Uint8Array(sub.options.applicationServerKey) : null;
      var same = current && current.length === key.length && current.every(function (v, i) { return v === key[i]; });
      if (!same) { await sub.unsubscribe(); sub = null; }
    }
    if (!sub) sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key });
    var res = await post({ action: "subscribe", subscription: sub.toJSON() });
    if (!res.ok) throw new Error("register failed");
    write(SYNC_KEY);
  }

  function ask(cfg, reg) {
    if (document.getElementById("btx-push")) return;
    var box = document.createElement("div");
    box.id = "btx-push";
    box.setAttribute("role", "region");
    box.setAttribute("aria-label", "New-mail notifications");
    box.style.cssText = chipCss(72);
    var label = document.createElement("span");
    label.textContent = "Get notified when new mail arrives";
    var go = button("Turn on", true);
    var no = button("✕", false);
    no.setAttribute("aria-label", "Not now");
    go.onclick = async function () {
      box.remove();
      try {
        var permission = await Notification.requestPermission();
        if (permission !== "granted") {
          dismissNow();
          toast("Notifications are blocked. Allow them in your browser settings to turn them on.");
          return;
        }
        await subscribe(cfg, reg);
        toast("Notifications are on for this device.");
      } catch (e) {
        toast("Could not turn on notifications. Please try again later.");
      }
    };
    no.onclick = function () { box.remove(); dismissNow(); };
    box.appendChild(label);
    box.appendChild(go);
    box.appendChild(no);
    document.body.appendChild(box);
  }

  // iPhone/iPad only deliver notifications to an app added to the Home Screen.
  function iosHint() {
    var ios = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
    if (!ios || standalone() || dismissedNow()) return;
    var box = document.createElement("div");
    box.setAttribute("role", "region");
    box.style.cssText = chipCss(72);
    var label = document.createElement("span");
    label.textContent = "For new-mail notifications: tap Share, then Add to Home Screen.";
    var no = button("✕", false);
    no.setAttribute("aria-label", "Dismiss");
    no.onclick = function () { box.remove(); dismissNow(); };
    box.appendChild(label);
    box.appendChild(no);
    document.body.appendChild(box);
  }

  async function init() {
    if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
      iosHint();
      return;
    }
    var res = await fetch(API, { credentials: "same-origin" });
    if (!res.ok) return; // not signed in as a mailbox owner, or push is not set up on the server
    var cfg = await res.json();
    if (!cfg.enabled || !cfg.public_key) return;
    var reg = await navigator.serviceWorker.ready;
    var sub = await reg.pushManager.getSubscription();
    if (Notification.permission === "granted") {
      // Already allowed: keep the device registered (once a day, and if the browser lost the subscription).
      if (!sub || Date.now() - read(SYNC_KEY) > DAY) await subscribe(cfg, reg);
      return;
    }
    if (Notification.permission === "denied" || dismissedNow()) return;
    ask(cfg, reg);
  }

  // Signing out stops notifications on this device, so a shared computer does not keep showing someone's mail.
  var originalLogout = window.mc_logout;
  window.mc_logout = async function () {
    try {
      var reg = await navigator.serviceWorker.getRegistration("/");
      var sub = reg && (await reg.pushManager.getSubscription());
      if (sub) {
        await post({ action: "unsubscribe", endpoint: sub.endpoint });
        await sub.unsubscribe();
      }
    } catch (e) { /* never block signing out */ }
    if (typeof originalLogout === "function") return originalLogout.apply(this, arguments);
  };

  window.addEventListener("load", function () {
    setTimeout(function () { init().catch(function () { /* push is optional */ }); }, 2500);
  });
})();
// <<< BThinkX PWA
