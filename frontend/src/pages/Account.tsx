import { useState, type FormEvent } from "react";

import { api, ApiError } from "../api";
import { useAuth, useMe } from "../auth";
import NotificationSettings from "../components/NotificationSettings";
import { Badge, errorText, Field, PageHead, PasswordInput, useToast } from "../components/ui";
import { ROLE_LABEL } from "../format";
import { PasswordChangeForm, RecoveryCodes } from "./Setup";

export default function Account() {
  const me = useMe();
  const { setMe } = useAuth();
  const toast = useToast();
  const [password, setPassword] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const regenerate = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      const res = await api.post<{ recovery_codes: string[] }>("/auth/2fa/recovery-codes/", { password });
      setCodes(res.recovery_codes);
      setPassword("");
    } catch (error) {
      setErr(error instanceof ApiError ? error.summary : errorText(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHead title="My account" intro={`${me.email} · ${ROLE_LABEL[me.role]}${me.business_name ? ` at ${me.business_name}` : ""}`} />
      <div className="two-col">
        <section className="panel">
          <div className="panel-head"><h2>Change password</h2></div>
          <div className="panel-body">
            <PasswordChangeForm
              onDone={(user) => {
                setMe(user);
                toast.ok("Password changed");
              }}
            />
          </div>
        </section>
        <section className="panel">
          <div className="panel-head">
            <h2>Two-factor authentication</h2>
            <Badge value={me.totp_enabled ? "OK" : "WARN"} label={me.totp_enabled ? "On" : "Off"} />
          </div>
          <div className="panel-body form">
            {codes ? (
              <RecoveryCodes codes={codes} />
            ) : (
              <form className="form" onSubmit={regenerate}>
                <p className="small">
                  Lost your recovery codes? Create a new set — the old codes stop working.
                </p>
                {err && <div className="notice bad">{err}</div>}
                <Field label="Confirm with your password">
                  {(id) => <PasswordInput id={id} autoComplete="current-password" value={password}
                                  onChange={(e) => setPassword(e.target.value)} required />}
                </Field>
                <button className="btn" disabled={busy || !password}>
                  {busy ? "Creating…" : "Create new recovery codes"}
                </button>
              </form>
            )}
            <p className="small muted">Lost your phone? Ask a BThinkX administrator to reset your two-factor setup.</p>
          </div>
        </section>
        <NotificationSettings />
      </div>
    </>
  );
}
