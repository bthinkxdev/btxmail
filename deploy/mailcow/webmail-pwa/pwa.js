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
  function dismissed() { try { return localStorage.getItem(KEY) === "1"; } catch (e) { return false; } }
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
      try { localStorage.setItem(KEY, "1"); } catch (e2) { /* ignore */ }
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
// <<< BThinkX PWA
