import { useState, type FormEvent, type ReactNode } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";

import { api, ApiError } from "../api";
import { useAuth } from "../auth";
import { Logo } from "../components/Layout";
import { errorText, Field } from "../components/ui";
import type { Me } from "../types";

export function AuthFrame({ children }: { children: ReactNode }) {
  return (
    <div className="auth">
      <section className="auth-art">
        <div className="brand" style={{ padding: 0 }}>
          <Logo /> BThinkX Mail
        </div>
        <div>
          <h1>Business email, sorted and delivered.</h1>
          <p>Manage domains, mailboxes and forwarding for your organisation. Reading mail? Use webmail instead.</p>
        </div>
        <div className="bigmark" aria-hidden="true">
          BTHINKX
          <br />
          MAIL
        </div>
      </section>
      <section className="auth-form">
        <div>{children}</div>
      </section>
    </div>
  );
}

type LoginResponse = { status: "ok"; user: Me } | { status: "otp_required" };

export default function Login() {
  const { me, setMe } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from ?? "/";
  const [step, setStep] = useState<"password" | "otp">("password");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  if (me && step === "password") return <Navigate to={me.setup_required ? "/setup" : from} replace />;

  const finish = (user: Me) => {
    setMe(user);
    navigate(user.setup_required ? "/setup" : from, { replace: true });
  };

  const submitPassword = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await api.post<LoginResponse>("/auth/login/", { email, password });
      setPassword("");
      if (res.status === "otp_required") setStep("otp");
      else finish(res.user);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  const submitCode = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await api.post<{ status: "ok"; user: Me }>("/auth/login/otp/", { code });
      finish(res.user);
    } catch (err) {
      setError(errorText(err));
      if (err instanceof ApiError && (err.code === "otp_expired" || err.code === "locked")) {
        setStep("password");
      }
      setCode("");
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthFrame>
      {step === "password" ? (
        <form className="form" onSubmit={submitPassword} noValidate>
          <div>
            <h2>Sign in to the admin portal</h2>
            <p className="sub">For BThinkX staff and business administrators.</p>
          </div>
          {error && (
            <div className="notice bad" role="alert">
              {error}
            </div>
          )}
          <Field label="E-mail">
            {(id) => (
              <input id={id} type="email" autoComplete="username" required value={email}
                     onChange={(e) => setEmail(e.target.value)} />
            )}
          </Field>
          <Field label="Password">
            {(id) => (
              <input id={id} type="password" autoComplete="current-password" required value={password}
                     onChange={(e) => setPassword(e.target.value)} />
            )}
          </Field>
          <button className="btn primary" type="submit" disabled={busy || !email || !password}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
          <Link to="/reset-password" className="small">
            Forgot your password?
          </Link>
        </form>
      ) : (
        <form className="form" onSubmit={submitCode} noValidate>
          <div>
            <h2>Enter your authentication code</h2>
            <p className="sub">Open your authenticator app, or use one of your recovery codes.</p>
          </div>
          {error && (
            <div className="notice bad" role="alert">
              {error}
            </div>
          )}
          <Field label="Code">
            {(id) => (
              <input id={id} inputMode="text" autoComplete="one-time-code" autoFocus required value={code}
                     maxLength={11} onChange={(e) => setCode(e.target.value.trim())} />
            )}
          </Field>
          <button className="btn primary" type="submit" disabled={busy || code.length < 6}>
            {busy ? "Checking…" : "Verify and sign in"}
          </button>
          <button type="button" className="btn link" onClick={() => setStep("password")}>
            Use a different account
          </button>
        </form>
      )}
    </AuthFrame>
  );
}
