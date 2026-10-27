import { useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router-dom";

import { api, ApiError } from "../api";
import { useAuth } from "../auth";
import { CopyButton, errorText, Field, Loading, PasswordInput } from "../components/ui";
import type { Me } from "../types";
import { AuthFrame } from "./Login";

export function PasswordChangeForm({ onDone }: { onDone: (me: Me) => void }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [err, setErr] = useState<ApiError | null>(null);
  const [mismatch, setMismatch] = useState(false);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (next !== repeat) {
      setMismatch(true);
      return;
    }
    setBusy(true);
    setErr(null);
    setMismatch(false);
    try {
      const me = await api.post<Me>("/auth/password/change/", { current_password: current, new_password: next });
      setCurrent("");
      setNext("");
      setRepeat("");
      onDone(me);
    } catch (error) {
      setErr(error instanceof ApiError ? error : new ApiError(0, errorText(error)));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="form" onSubmit={submit}>
      {err && !err.field("current_password") && !err.field("new_password") && (
        <div className="notice bad">{err.summary}</div>
      )}
      <Field label="Current password" error={err?.field("current_password")}>
        {(id) => <PasswordInput id={id} autoComplete="current-password" value={current}
                        onChange={(e) => setCurrent(e.target.value)} required />}
      </Field>
      <Field label="New password" hint="At least 12 characters, not a common password." error={err?.field("new_password")}>
        {(id) => <PasswordInput id={id} autoComplete="new-password" value={next}
                        onChange={(e) => setNext(e.target.value)} required minLength={12} />}
      </Field>
      <Field label="Repeat new password" error={mismatch ? "The two passwords do not match." : undefined}>
        {(id) => <PasswordInput id={id} autoComplete="new-password" value={repeat}
                        onChange={(e) => setRepeat(e.target.value)} required />}
      </Field>
      <button className="btn primary" disabled={busy || !current || next.length < 12}>
        {busy ? "Saving…" : "Change password"}
      </button>
    </form>
  );
}

export function TwoFactorEnrol({ onDone }: { onDone: (me: Me, codes: string[]) => void }) {
  const [setup, setSetup] = useState<{ secret: string; qr_svg: string; otpauth_uri: string } | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const start = async () => {
    setBusy(true);
    setError("");
    try {
      setSetup(await api.post("/auth/2fa/setup/"));
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  const confirm = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await api.post<{ recovery_codes: string[]; user: Me }>("/auth/2fa/enable/", { code });
      onDone(res.user, res.recovery_codes);
    } catch (err) {
      setError(errorText(err));
      setCode("");
    } finally {
      setBusy(false);
    }
  };

  if (!setup) {
    return (
      <div className="form">
        <p className="sub">
          Admin accounts must use an authenticator app (Google Authenticator, Microsoft Authenticator, 1Password,
          Authy…) in addition to the password.
        </p>
        {error && <div className="notice bad">{error}</div>}
        <button className="btn primary" onClick={start} disabled={busy}>
          {busy ? "Preparing…" : "Set up authenticator app"}
        </button>
      </div>
    );
  }
  return (
    <form className="form" onSubmit={confirm}>
      <p>Scan this code with your authenticator app, then enter the 6-digit code it shows.</p>
      {/* SVG generated server-side by the qrcode library from our own otpauth URI */}
      <div className="qr" dangerouslySetInnerHTML={{ __html: setup.qr_svg }} aria-label="QR code" role="img" />
      <div className="small">
        Can't scan? Enter this key manually:
        <div className="secret" style={{ marginTop: 6 }}>
          <span>{setup.secret}</span>
          <CopyButton value={setup.secret} />
        </div>
      </div>
      {error && <div className="notice bad">{error}</div>}
      <Field label="6-digit code">
        {(id) => <input id={id} inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code}
                        onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} required />}
      </Field>
      <button className="btn primary" disabled={busy || code.length !== 6}>
        {busy ? "Checking…" : "Turn on two-factor authentication"}
      </button>
    </form>
  );
}

export function RecoveryCodes({ codes }: { codes: string[] }) {
  return (
    <div className="form">
      <div className="notice warn">
        <strong>Save your recovery codes</strong>
        Each code signs you in once if you lose your phone. Store them in a password manager — they will not be
        shown again.
      </div>
      <div className="codes">
        {codes.map((c) => (
          <span key={c}>{c}</span>
        ))}
      </div>
      <CopyButton value={codes.join("\n")} label="Copy all codes" />
    </div>
  );
}

export default function Setup() {
  const { me, loading, setMe } = useAuth();
  const navigate = useNavigate();
  const [codes, setCodes] = useState<string[] | null>(null);

  if (loading) return <Loading />;
  if (!me) return <Navigate to="/login" replace />;
  if (!me.setup_required && !codes) return <Navigate to="/" replace />;

  return (
    <AuthFrame>
      {codes ? (
        <div className="form">
          <h2>Two-factor authentication is on</h2>
          <RecoveryCodes codes={codes} />
          <button className="btn primary" onClick={() => navigate("/", { replace: true })}>
            I have saved my codes — continue
          </button>
        </div>
      ) : me.setup_required === "password_change_required" ? (
        <div className="form">
          <div>
            <h2>Choose your own password</h2>
            <p className="sub">You signed in with a temporary password. Replace it to continue.</p>
          </div>
          <PasswordChangeForm onDone={setMe} />
        </div>
      ) : (
        <div className="form">
          <h2>Protect your account</h2>
          <TwoFactorEnrol
            onDone={(user, recovery) => {
              setCodes(recovery);
              setMe(user);
            }}
          />
        </div>
      )}
    </AuthFrame>
  );
}
