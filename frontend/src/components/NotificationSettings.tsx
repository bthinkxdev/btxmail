import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, qs } from "../api";
import { useMe } from "../auth";
import { useInstall, useStandalone } from "../pwa";
import { usePush } from "../push";
import type { Mailbox, Page } from "../types";
import { Badge, errorText, useToast } from "./ui";

interface Preferences {
  new_mail: boolean;
  security: boolean;
  domains: boolean;
  system: boolean;
  watched_mailboxes: number[];
  own_mailboxes: number[];
  devices: number;
}

export default function NotificationSettings() {
  const me = useMe();
  const toast = useToast();
  const client = useQueryClient();
  const push = usePush();
  const install = useInstall();
  const standalone = useStandalone();
  const [saving, setSaving] = useState(false);

  const prefs = useQuery({ queryKey: ["push-prefs"], queryFn: () => api.get<Preferences>("/notifications/preferences/") });
  const mailboxes = useQuery({
    queryKey: ["push-mailboxes"],
    queryFn: () => api.get<Page<Mailbox>>(`/mailboxes/${qs({ page_size: 200 })}`),
  });

  const save = async (patch: Partial<Preferences>) => {
    setSaving(true);
    try {
      client.setQueryData(["push-prefs"], await api.patch<Preferences>("/notifications/preferences/", patch));
    } catch (e) {
      toast.error(e);
    } finally {
      setSaving(false);
    }
  };

  const guard = async (fn: () => Promise<void>, ok: string) => {
    try {
      await fn();
      void client.invalidateQueries({ queryKey: ["push-prefs"] });
      toast.ok(ok);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : errorText(e));
    }
  };

  const iosNeedsInstall = install.kind === "ios" && !standalone;
  const p = prefs.data;
  const watched = new Set(p?.watched_mailboxes ?? []);
  const toggleWatch = (id: number) => {
    const next = new Set(watched);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    void save({ watched_mailboxes: [...next] });
  };

  const status = !push.supported
    ? { value: "WARN", label: "Not supported" }
    : push.permission === "denied"
      ? { value: "FAIL", label: "Blocked" }
      : push.subscribed
        ? { value: "OK", label: "On for this device" }
        : { value: "WARN", label: "Off" };

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Notifications</h2>
        <Badge value={status.value} label={status.label} />
      </div>
      <div className="panel-body form">
        {iosNeedsInstall ? (
          <div className="notice">
            On iPhone and iPad, notifications work once the app is on your home screen: tap Share, choose “Add to Home
            Screen”, then open BThinkX Mail from there.
          </div>
        ) : !push.supported ? (
          <div className="notice">This browser does not support notifications. Use a current Chrome, Edge, Firefox or Safari.</div>
        ) : push.permission === "denied" ? (
          <div className="notice bad">
            Notifications are blocked for this site. Allow them in your browser’s site settings, then come back.
          </div>
        ) : (
          <div className="actions">
            {push.subscribed ? (
              <>
                <button className="btn" disabled={push.busy} onClick={() => void guard(async () => {
                  await api.post("/notifications/test/");
                }, "Test notification sent")}>
                  Send a test
                </button>
                <button className="btn" disabled={push.busy} onClick={() => void guard(push.disable, "Notifications turned off on this device")}>
                  Turn off on this device
                </button>
              </>
            ) : (
              <button className="btn primary" disabled={push.busy} onClick={() => void guard(push.enable, "Notifications turned on")}>
                {push.busy ? "Turning on…" : "Turn on notifications"}
              </button>
            )}
          </div>
        )}

        {p && (
          <>
            <p className="small muted">
              {p.devices} {p.devices === 1 ? "device" : "devices"} registered for your account.
            </p>
            <fieldset className="check-group" disabled={saving}>
              <legend className="small">Notify me about</legend>
              <label className="check">
                <input type="checkbox" checked={p.new_mail} onChange={(e) => void save({ new_mail: e.target.checked })} />
                New mail in the mailboxes I follow
              </label>
              <label className="check">
                <input type="checkbox" checked={p.security} onChange={(e) => void save({ security: e.target.checked })} />
                Security events, such as blocked sending
              </label>
              <label className="check">
                <input type="checkbox" checked={p.domains} onChange={(e) => void save({ domains: e.target.checked })} />
                Domain setup and DNS problems
              </label>
              {me.is_platform_staff && (
                <label className="check">
                  <input type="checkbox" checked={p.system} onChange={(e) => void save({ system: e.target.checked })} />
                  Mail server and system alerts
                </label>
              )}
            </fieldset>

            <fieldset className="check-group" disabled={saving || !p.new_mail}>
              <legend className="small">Mailboxes I follow</legend>
              {(mailboxes.data?.results ?? []).map((m) => {
                const own = p.own_mailboxes.includes(m.id);
                return (
                  <label key={m.id} className="check">
                    <input type="checkbox" checked={own || watched.has(m.id)} disabled={own} onChange={() => toggleWatch(m.id)} />
                    {m.email}
                    {own && <span className="muted"> · your own mailbox</span>}
                  </label>
                );
              })}
              {mailboxes.data && mailboxes.data.results.length === 0 && <p className="small muted">There are no mailboxes yet.</p>}
            </fieldset>
          </>
        )}
      </div>
    </section>
  );
}
