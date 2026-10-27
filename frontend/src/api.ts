/**
 * Thin fetch wrapper for the Django API.
 * - Same-origin session cookie; CSRF token read from the `btx_csrftoken` cookie.
 * - Errors are normalised into ApiError with the server's `detail`/`code`/`errors`.
 */

export class ApiError extends Error {
  status: number;
  code: string;
  errors?: Record<string, string[] | string>;
  requestId?: string;

  constructor(status: number, message: string, code = "error", errors?: Record<string, string[] | string>, requestId?: string) {
    super(message);
    this.status = status;
    this.code = code;
    this.errors = errors;
    this.requestId = requestId;
  }

  /** First error message for a form field, if any. */
  field(name: string): string | undefined {
    const v = this.errors?.[name];
    if (!v) return undefined;
    return Array.isArray(v) ? v[0] : String(v);
  }

  /** A readable summary including field errors. */
  get summary(): string {
    if (!this.errors) return this.message;
    const parts = Object.entries(this.errors).map(([k, v]) => {
      const msg = Array.isArray(v) ? v.join(" ") : typeof v === "string" ? v : JSON.stringify(v);
      return k === "non_field_errors" || k === "detail" ? msg : `${k.replace(/_/g, " ")}: ${msg}`;
    });
    return parts.join(" ");
  }
}

function getCookie(name: string): string | null {
  const match = document.cookie.split("; ").find((row) => row.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.split("=").slice(1).join("=")) : null;
}

let csrfReady: Promise<void> | null = null;

export function ensureCsrf(force = false): Promise<void> {
  if (!force && getCookie("btx_csrftoken")) return Promise.resolve();
  if (!csrfReady || force) {
    csrfReady = fetch("/api/auth/csrf/", { credentials: "same-origin" }).then(() => undefined);
  }
  return csrfReady;
}

type Method = "GET" | "POST" | "PATCH" | "DELETE";

async function request<T>(method: Method, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (method !== "GET") {
    await ensureCsrf();
    headers["X-CSRFToken"] = getCookie("btx_csrftoken") ?? "";
    headers["Content-Type"] = "application/json";
  }
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      method,
      headers,
      credentials: "same-origin",
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "Cannot reach the server. Check your connection and try again.", "network");
  }

  if (response.status === 204) return undefined as T;

  let data: unknown = null;
  const text = await response.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }

  if (!response.ok) {
    const d = (data ?? {}) as { detail?: string; code?: string; errors?: Record<string, string[]>; request_id?: string };
    const fallback =
      response.status === 429
        ? "Too many requests. Wait a moment and try again."
        : response.status >= 500
          ? "The server could not complete the request."
          : "The request was not accepted.";
    const err = new ApiError(response.status, d.detail || fallback, d.code || "error", d.errors, d.request_id);
    if (response.status === 403 && (d.code === "not_authenticated" || d.detail?.includes("credentials"))) {
      window.dispatchEvent(new CustomEvent("btx:unauthenticated"));
    }
    throw err;
  }
  return data as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {}),
  patch: <T>(path: string, body: unknown) => request<T>("PATCH", path, body),
  del: (path: string, body?: unknown) => request<void>("DELETE", path, body),
};

export function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}
