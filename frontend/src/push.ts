import { useCallback, useEffect, useState } from "react";

import { api } from "./api";

const FLAG = "btx-push-enabled";

export function pushSupported(): boolean {
  return (
    import.meta.env.PROD &&
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    "Notification" in window
  );
}

function keyToBytes(base64Url: string): Uint8Array<ArrayBuffer> {
  const padded = base64Url + "=".repeat((4 - (base64Url.length % 4)) % 4);
  const raw = atob(padded.replace(/-/g, "+").replace(/_/g, "/"));
  const bytes = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
  return bytes;
}

function sameKey(sub: PushSubscription, key: Uint8Array): boolean {
  const current = sub.options.applicationServerKey;
  if (!current) return false;
  const a = new Uint8Array(current);
  return a.length === key.length && a.every((v, i) => v === key[i]);
}

interface PushConfig {
  enabled: boolean;
  public_key: string;
}

async function registration() {
  return navigator.serviceWorker.ready;
}

export async function currentSubscription(): Promise<PushSubscription | null> {
  if (!pushSupported()) return null;
  return (await registration()).pushManager.getSubscription();
}

/** Ask permission (must be called from a click), subscribe this device and register it with the server. */
export async function enablePush(): Promise<void> {
  const config = await api.get<PushConfig>("/notifications/config/");
  if (!config.enabled) throw new Error("Notifications are not available on this server yet.");
  const permission = await Notification.requestPermission();
  if (permission !== "granted") {
    throw new Error("Notifications are blocked. Allow them for this site in your browser settings, then try again.");
  }
  const key = keyToBytes(config.public_key);
  const reg = await registration();
  let sub = await reg.pushManager.getSubscription();
  if (sub && !sameKey(sub, key)) {
    await sub.unsubscribe();
    sub = null;
  }
  sub ??= await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key });
  await api.post("/notifications/subscriptions/", sub.toJSON());
  try {
    localStorage.setItem(FLAG, "1");
  } catch {
    /* storage unavailable */
  }
}

/** Remove this device from the server and the browser. Safe to call when nothing is subscribed. */
export async function disablePush(): Promise<void> {
  try {
    localStorage.removeItem(FLAG);
  } catch {
    /* storage unavailable */
  }
  const sub = await currentSubscription();
  if (!sub) return;
  try {
    await api.del("/notifications/subscriptions/", { endpoint: sub.endpoint });
  } finally {
    await sub.unsubscribe();
  }
}

/** After a browser-side change (key rotation, expiry) re-register silently; permission is already granted. */
export async function syncPushSubscription(): Promise<void> {
  if (!pushSupported() || Notification.permission !== "granted") return;
  let enabled = false;
  try {
    enabled = localStorage.getItem(FLAG) === "1";
  } catch {
    return;
  }
  if (!enabled) return;
  try {
    await enablePush();
  } catch {
    /* retried on the next visit */
  }
}

export interface PushState {
  supported: boolean;
  permission: NotificationPermission | "unsupported";
  subscribed: boolean;
  busy: boolean;
  enable: () => Promise<void>;
  disable: () => Promise<void>;
}

export function usePush(): PushState {
  const supported = pushSupported();
  const [permission, setPermission] = useState<NotificationPermission | "unsupported">(
    supported ? Notification.permission : "unsupported",
  );
  const [subscribed, setSubscribed] = useState(false);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    if (!supported) return;
    setPermission(Notification.permission);
    setSubscribed((await currentSubscription()) !== null && Notification.permission === "granted");
  }, [supported]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const run = useCallback(
    async (fn: () => Promise<void>) => {
      setBusy(true);
      try {
        await fn();
      } finally {
        setBusy(false);
        await refresh();
      }
    },
    [refresh],
  );

  return {
    supported,
    permission,
    subscribed,
    busy,
    enable: () => run(enablePush),
    disable: () => run(disablePush),
  };
}
