import { useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api, ApiError } from "../api";
import { errorText, Field, PasswordInput } from "../components/ui";
import { AuthFrame } from "./Login";

export default function ResetPassword() {
  const [params] = useSearchParams();
  const uid = params.get("uid");
  const token = params.get("token");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [fieldError, setFieldError] = useState<string | undefined>();
  const [busy, setBusy] = useState(false);

  const requestLink = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await api.post<{ detail: string }>("/auth/password/reset/", { email });
      setMessage(res.detail);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  const setNew = async (e: FormEvent) => {
    e.preventDefault();
    if (password !== confirm) {
      setFieldError("The two passwords do not match.");
      return;
    }
    setBusy(true);
    setError("");
    setFieldError(undefined);
    try {
      const res = await api.post<{ detail: string }>("/auth/password/reset/confirm/", {
        uid,
        token,
        new_password: password,
      });
      setMessage(res.detail);
    } catch (err) {
      if (err instanceof ApiError && err.field("new_password")) setFieldError(err.field("new_password"));
      else setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthFrame>
      {message ? (
        <div className="form">
          <h2>Check complete</h2>
          <div className="notice ok">{message}</div>
          <Link to="/login" className="btn primary">
            Back to sign in
          </Link>
        </div>
      ) : uid && token ? (
        <form className="form" onSubmit={setNew}>
          <div>
            <h2>Choose a new password</h2>
            <p className="sub">At least 12 characters. Avoid passwords you use elsewhere.</p>
          </div>
          {error && <div className="notice bad">{error}</div>}
          <Field label="New password" error={fieldError}>
            {(id) => (
              <PasswordInput id={id} autoComplete="new-password" required minLength={12} value={password}
                     onChange={(e) => setPassword(e.target.value)} />
            )}
          </Field>
          <Field label="Repeat new password">
            {(id) => (
              <PasswordInput id={id} autoComplete="new-password" required value={confirm}
                     onChange={(e) => setConfirm(e.target.value)} />
            )}
          </Field>
          <button className="btn primary" disabled={busy || password.length < 12}>
            {busy ? "Saving…" : "Save new password"}
          </button>
        </form>
      ) : (
        <form className="form" onSubmit={requestLink}>
          <div>
            <h2>Reset your password</h2>
            <p className="sub">We will e-mail a link that works for one hour.</p>
          </div>
          {error && <div className="notice bad">{error}</div>}
          <Field label="E-mail">
            {(id) => (
              <input id={id} type="email" autoComplete="username" required value={email}
                     onChange={(e) => setEmail(e.target.value)} />
            )}
          </Field>
          <button className="btn primary" disabled={busy || !email}>
            {busy ? "Sending…" : "Send reset link"}
          </button>
          <Link to="/login" className="small">
            Back to sign in
          </Link>
        </form>
      )}
    </AuthFrame>
  );
}
