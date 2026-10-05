import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { ApiError } from "../api";
import { humanize } from "../format";

/* ------------------------------------------------------------------ toasts */
interface Toast {
  id: number;
  text: string;
  error?: boolean;
}
const ToastContext = createContext<(text: string, error?: boolean) => void>(() => undefined);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((text: string, error = false) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, text, error }]);
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), error ? 8000 : 4000);
  }, []);
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast${t.error ? " error" : ""}`}>
            {t.text}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const push = useContext(ToastContext);
  return {
    ok: (text: string) => push(text),
    error: (err: unknown) => push(errorText(err), true),
  };
}

export function errorText(err: unknown): string {
  if (err instanceof ApiError) return err.summary;
  if (err instanceof Error) return err.message;
  return "Something went wrong.";
}

/* ------------------------------------------------------------------ status badges */
const TONE: Record<string, "ok" | "bad" | "warn" | "info" | ""> = {
  ACTIVE: "ok",
  PASS: "ok",
  OK: "ok",
  HEALTHY: "ok",
  SUSPENDED: "bad",
  DISABLED: "",
  FAILED: "bad",
  FAIL: "bad",
  CRITICAL: "bad",
  HIGH: "bad",
  LISTED: "bad",
  PROVISIONING_FAILED: "bad",
  CLOSED: "",
  PENDING: "info",
  PENDING_VERIFICATION: "info",
  PROVISIONING: "info",
  DNS_PENDING: "warn",
  WARN: "warn",
  WARNING: "warn",
  MEDIUM: "warn",
  DELETING: "warn",
  LOW: "",
  UNKNOWN: "",
  INFO: "info",
};

const LABEL: Record<string, string> = {
  PENDING_VERIFICATION: "Awaiting verification",
  DNS_PENDING: "Awaiting DNS",
  PROVISIONING_FAILED: "Setup failed",
  UNKNOWN: "Not checked",
};

export function Badge({ value, label }: { value: string; label?: string }) {
  return <span className={`badge ${TONE[value] ?? ""}`}>{label ?? LABEL[value] ?? humanize(value)}</span>;
}

/* ------------------------------------------------------------------ layout bits */
export function PageHead({ title, intro, children, crumb }: {
  title: string;
  intro?: ReactNode;
  children?: ReactNode;
  crumb?: ReactNode;
}) {
  return (
    <header className="page-head">
      <div>
        {crumb}
        <h1>{title}</h1>
        {intro && <p>{intro}</p>}
      </div>
      {children && <div className="actions">{children}</div>}
    </header>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return <div className="spinner">{label}</div>;
}

export function ErrorNotice({ error }: { error: unknown }) {
  return (
    <div className="notice bad" role="alert">
      <strong>Could not load this page</strong>
      {errorText(error)}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function Meter({ value, max }: { value: number; max: number }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  const cls = pct >= 95 ? "full" : pct >= 80 ? "high" : "";
  return (
    <div className={`meter ${cls}`} role="meter" aria-valuemin={0} aria-valuemax={max} aria-valuenow={value}>
      <span style={{ width: `${pct}%` }} />
    </div>
  );
}

export function Pager({ count, page, pageSize, onPage }: {
  count: number;
  page: number;
  pageSize: number;
  onPage: (p: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(count / pageSize));
  if (pages <= 1) return null;
  return (
    <div className="pager">
      <span>
        Page {page} of {pages} · {count} total
      </span>
      <div className="actions">
        <button className="btn small" disabled={page <= 1} onClick={() => onPage(page - 1)}>
          Previous
        </button>
        <button className="btn small" disabled={page >= pages} onClick={() => onPage(page + 1)}>
          Next
        </button>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ form field */
export function Field({ label, hint, error, children, id }: {
  label: string;
  hint?: ReactNode;
  error?: string;
  children: (id: string) => ReactNode;
  id?: string;
}) {
  const auto = useId();
  const fid = id ?? auto;
  return (
    <div className="field">
      <label htmlFor={fid}>{label}</label>
      {children(fid)}
      {hint && !error && <span className="hint">{hint}</span>}
      {error && (
        <span className="err" role="alert">
          {error}
        </span>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ dialog */
export function Dialog({ title, onClose, children, footer }: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    // Runs once per open: focus the first control, close on Escape, restore focus on close.
    const previous = document.activeElement as HTMLElement | null;
    const first = ref.current?.querySelector<HTMLElement>("input, select, textarea, button:not(.dlg-x)");
    first?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeRef.current();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      previous?.focus();
    };
  }, []);
  return (
    <div className="backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog" role="dialog" aria-modal="true" aria-labelledby={titleId} ref={ref}>
        <div className="dialog-head">
          <h2 id={titleId}>{title}</h2>
          <button className="dlg-x" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <div className="dialog-body">{children}</div>
        {footer && <div className="dialog-foot">{footer}</div>}
      </div>
    </div>
  );
}

/** Confirmation dialog for destructive actions. Requires typing the object name when `confirmText` is set. */
export function Confirm({ title, body, action, danger, confirmText, onConfirm, onClose, busy }: {
  title: string;
  body: ReactNode;
  action: string;
  danger?: boolean;
  confirmText?: string;
  onConfirm: () => void;
  onClose: () => void;
  busy?: boolean;
}) {
  const [typed, setTyped] = useState("");
  const blocked = Boolean(confirmText) && typed.trim().toLowerCase() !== confirmText?.toLowerCase();
  return (
    <Dialog
      title={title}
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose}>
            Cancel
          </button>
          <button
            className={`btn ${danger ? "danger solid" : "primary"}`}
            disabled={blocked || busy}
            onClick={onConfirm}
          >
            {busy ? "Working…" : action}
          </button>
        </>
      }
    >
      <div className="form">
        <div>{body}</div>
        {confirmText && (
          <Field label={`Type ${confirmText} to confirm`}>
            {(id) => <input id={id} value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" />}
          </Field>
        )}
      </div>
    </Dialog>
  );
}

/* ------------------------------------------------------------------ copy + secrets */
export function CopyButton({ value, label = "Copy" }: { value: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      className="btn small"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
          setDone(true);
          window.setTimeout(() => setDone(false), 1500);
        } catch {
          /* clipboard blocked: the value stays selectable */
        }
      }}
    >
      {done ? "Copied" : label}
    </button>
  );
}

/** A one-time secret (temporary password). Shown once; never stored client-side. */
export function SecretReveal({ title, value, children }: { title: string; value: string; children?: ReactNode }) {
  return (
    <div className="form">
      <div className="notice warn">
        <strong>{title}</strong>
        This is the only time it will be shown. Share it through a separate channel; the user must change it at
        first sign-in.
      </div>
      <div className="secret">
        <span>{value}</span>
        <CopyButton value={value} />
      </div>
      {children}
    </div>
  );
}
