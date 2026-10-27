import { useCallback, useEffect, useState } from "react";

interface InstallPromptEvent extends Event {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

let waiting: ServiceWorker | null = null;
const updateListeners = new Set<(ready: boolean) => void>();

function announceUpdate(worker: ServiceWorker | null) {
  waiting = worker;
  updateListeners.forEach((fn) => fn(worker !== null));
}

/** Registers the service worker (production builds only). */
export function registerServiceWorker() {
  if (!("serviceWorker" in navigator) || !import.meta.env.PROD) return;
  window.addEventListener("load", () => {
    navigator.serviceWorker
      .register("/sw.js", { scope: "/", updateViaCache: "none" })
      .then((reg) => {
        if (reg.waiting && navigator.serviceWorker.controller) announceUpdate(reg.waiting);
        reg.addEventListener("updatefound", () => {
          const worker = reg.installing;
          worker?.addEventListener("statechange", () => {
            if (worker.state === "installed" && navigator.serviceWorker.controller) announceUpdate(worker);
          });
        });
        // Look for a new version when the app returns to the foreground and hourly.
        document.addEventListener("visibilitychange", () => {
          if (document.visibilityState === "visible") void reg.update();
        });
        window.setInterval(() => void reg.update(), 60 * 60 * 1000);
      })
      .catch(() => undefined);
  });
  let reloading = false;
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (reloading) return;
    reloading = true;
    window.location.reload();
  });
}

export function useOnline(): boolean {
  const [online, setOnline] = useState(() => navigator.onLine);
  useEffect(() => {
    const on = () => setOnline(true);
    const off = () => setOnline(false);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    return () => {
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
    };
  }, []);
  return online;
}

function isStandalone(): boolean {
  return (
    window.matchMedia("(display-mode: standalone)").matches ||
    (navigator as Navigator & { standalone?: boolean }).standalone === true
  );
}

function isIosSafari(): boolean {
  const ua = navigator.userAgent;
  return /iPad|iPhone|iPod/.test(ua) && !/CriOS|FxiOS|EdgiOS/.test(ua);
}

export type InstallState = { kind: "installed" } | { kind: "prompt"; install: () => void } | { kind: "ios" } | { kind: "manual" };

export function useStandalone(): boolean {
  return isStandalone();
}

export function useInstall(): InstallState {
  const [event, setEvent] = useState<InstallPromptEvent | null>(null);
  const [installed, setInstalled] = useState(isStandalone);
  useEffect(() => {
    const onPrompt = (e: Event) => {
      e.preventDefault();
      setEvent(e as InstallPromptEvent);
    };
    const onInstalled = () => {
      setInstalled(true);
      setEvent(null);
    };
    window.addEventListener("beforeinstallprompt", onPrompt);
    window.addEventListener("appinstalled", onInstalled);
    return () => {
      window.removeEventListener("beforeinstallprompt", onPrompt);
      window.removeEventListener("appinstalled", onInstalled);
    };
  }, []);
  const install = useCallback(() => {
    if (!event) return;
    void event.prompt();
    void event.userChoice.then(() => setEvent(null));
  }, [event]);

  if (installed) return { kind: "installed" };
  if (event) return { kind: "prompt", install };
  if (isIosSafari()) return { kind: "ios" };
  return { kind: "manual" };
}

/** Offline notice and "new version" bar, shown above everything else. */
export function PwaStatus() {
  const online = useOnline();
  const [updateReady, setUpdateReady] = useState(waiting !== null);
  useEffect(() => {
    updateListeners.add(setUpdateReady);
    return () => void updateListeners.delete(setUpdateReady);
  }, []);
  return (
    <>
      {!online && (
        <div className="pwa-bar offline" role="status">
          You're offline. Changes can't be saved until your connection returns.
        </div>
      )}
      {updateReady && (
        <div className="pwa-bar update" role="status">
          <span>A new version is available.</span>
          <button type="button" onClick={() => waiting?.postMessage("SKIP_WAITING")}>
            Update now
          </button>
        </div>
      )}
    </>
  );
}
