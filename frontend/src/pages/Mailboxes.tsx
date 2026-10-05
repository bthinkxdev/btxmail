import { useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";

import { api, ApiError } from "../api";
import { useMe } from "../auth";
import {
  Badge,
  Confirm,
  Dialog,
  Empty,
  ErrorNotice,
  Field,
  Loading,
  Meter,
  PageHead,
  Pager,
  SecretReveal,
} from "../components/ui";
import { formatBytes, formatMb, relative } from "../format";
import { PAGE_SIZE, useAction, useApiGet, useDebounced, usePaged } from "../hooks";
import type { Domain, Mailbox, Page } from "../types";

function useMailDomains() {
  const q = useApiGet<Page<Domain>>("/domains/?page_size=200");
  return (q.data?.results ?? []).filter((d) => d.mailcow_provisioned && d.status !== "SUSPENDED");
}

function CreateMailbox({ onClose, presetDomain }: { onClose: () => void; presetDomain?: string }) {
  const domains = useMailDomains();
  const [domain, setDomain] = useState(presetDomain ?? "");
  const [local, setLocal] = useState("");
  const [name, setName] = useState("");
  const [quota, setQuota] = useState("");
  const [created, setCreated] = useState<Mailbox | null>(null);
  const domainId = domain || (domains.length === 1 ? String(domains[0]?.id) : "");
  const chosen = domains.find((d) => String(d.id) === domainId);

  const create = useAction(
    (body: Record<string, unknown>) => api.post<Mailbox>("/mailboxes/", body),
    { success: (m) => `${m.email} created`, onSuccess: setCreated },
  );
  const err = create.error instanceof ApiError ? create.error : null;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate({
      domain: Number(domainId),
      local_part: local,
      display_name: name,
      ...(quota ? { quota_mb: Number(quota) } : {}),
    });
  };

  if (created?.temporary_password) {
    return (
      <Dialog title="Mailbox created" onClose={onClose} footer={<button className="btn primary" onClick={onClose}>Done</button>}>
        <SecretReveal title={`Temporary password for ${created.email}`} value={created.temporary_password}>
          <p className="small">
            The user signs in at <a href={created.webmail_url} target="_blank" rel="noreferrer">{created.webmail_url}</a>{" "}
            and is asked to choose a new password. Phones and Outlook can use the same address and password.
          </p>
        </SecretReveal>
      </Dialog>
    );
  }

  return (
    <Dialog
      title="Create mailbox"
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" form="mb-create" disabled={create.isPending || !local || !domainId}>
            {create.isPending ? "Creating…" : "Create mailbox"}
          </button>
        </>
      }
    >
      {domains.length === 0 ? (
        <div className="notice info">
          <strong>No domain is ready yet</strong>
          Add a domain and verify it before creating mailboxes.
        </div>
      ) : (
        <form id="mb-create" className="form" onSubmit={submit}>
          {err && !err.errors && <div className="notice bad">{err.message}</div>}
          {domains.length > 1 && (
            <Field label="Domain" error={err?.field("domain")}>
              {(id) => (
                <select id={id} value={domainId} onChange={(e) => setDomain(e.target.value)} required>
                  <option value="">Choose a domain</option>
                  {domains.map((d) => (
                    <option key={d.id} value={d.id}>{d.name}{d.status !== "ACTIVE" ? " (DNS not finished)" : ""}</option>
                  ))}
                </select>
              )}
            </Field>
          )}
          <Field label="E-mail address" error={err?.field("local_part")}>
            {(id) => (
              <div className="input-suffix">
                <input id={id} value={local} onChange={(e) => setLocal(e.target.value.toLowerCase())} placeholder="sales"
                       autoComplete="off" spellCheck={false} required maxLength={64} />
                <span>@{chosen?.name ?? "domain"}</span>
              </div>
            )}
          </Field>
          <Field label="Display name" hint="Shown to recipients, e.g. Sales Department." error={err?.field("display_name")}>
            {(id) => <input id={id} value={name} onChange={(e) => setName(e.target.value)} maxLength={200} />}
          </Field>
          <Field label="Storage (MB)" hint={quota ? formatMb(Number(quota)) : "Leave empty for your plan's default."}
                 error={err?.field("quota_mb")}>
            {(id) => <input id={id} type="number" min={1} step={256} value={quota} onChange={(e) => setQuota(e.target.value)} />}
          </Field>
          {chosen && chosen.status !== "ACTIVE" && (
            <div className="notice warn small">
              {chosen.name} has not finished DNS setup. The mailbox works, but it will only receive outside mail once
              the MX record is live.
            </div>
          )}
          <p className="small muted">A temporary password is generated and shown once after creation.</p>
        </form>
      )}
    </Dialog>
  );
}

function EditMailbox({ mailbox, onClose }: { mailbox: Mailbox; onClose: () => void }) {
  const me = useMe();
  const [name, setName] = useState(mailbox.display_name);
  const [quota, setQuota] = useState(String(mailbox.quota_mb));
  const [perHour, setPerHour] = useState(mailbox.outbound_limit_per_hour ? String(mailbox.outbound_limit_per_hour) : "");
  const [perDay, setPerDay] = useState(mailbox.outbound_limit_per_day ? String(mailbox.outbound_limit_per_day) : "");
  const save = useAction((body: Record<string, unknown>) => api.patch<Mailbox>(`/mailboxes/${mailbox.id}/`, body), {
    success: "Mailbox saved",
    onSuccess: onClose,
  });
  const err = save.error instanceof ApiError ? save.error : null;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const body: Record<string, unknown> = { display_name: name, quota_mb: Number(quota) };
    if (me.is_platform_staff) {
      body.outbound_limit_per_hour = perHour ? Number(perHour) : null;
      body.outbound_limit_per_day = perDay ? Number(perDay) : null;
    }
    save.mutate(body);
  };

  return (
    <Dialog
      title={`Edit ${mailbox.email}`}
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" form="mb-edit" disabled={save.isPending}>
            {save.isPending ? "Saving…" : "Save changes"}
          </button>
        </>
      }
    >
      <form id="mb-edit" className="form" onSubmit={submit}>
        {err && !err.errors && <div className="notice bad">{err.message}</div>}
        <Field label="Display name" error={err?.field("display_name")}>
          {(id) => <input id={id} value={name} onChange={(e) => setName(e.target.value)} maxLength={200} />}
        </Field>
        <Field label="Storage (MB)" hint={`${formatMb(Number(quota) || 0)} · ${formatBytes(mailbox.used_bytes)} used`}
               error={err?.field("quota_mb")}>
          {(id) => <input id={id} type="number" min={1} value={quota} onChange={(e) => setQuota(e.target.value)} required />}
        </Field>
        {me.is_platform_staff && (
          <div className="form-row">
            <Field label="Sending limit per hour" hint={`Plan default: ${mailbox.effective_limit_per_hour}`}
                   error={err?.field("outbound_limit_per_hour")}>
              {(id) => <input id={id} type="number" min={1} value={perHour} placeholder="Plan default"
                              onChange={(e) => setPerHour(e.target.value)} />}
            </Field>
            <Field label="Sending limit per day" hint={`Plan default: ${mailbox.effective_limit_per_day}`}
                   error={err?.field("outbound_limit_per_day")}>
              {(id) => <input id={id} type="number" min={1} value={perDay} placeholder="Plan default"
                              onChange={(e) => setPerDay(e.target.value)} />}
            </Field>
          </div>
        )}
      </form>
    </Dialog>
  );
}

const DONE_TEXT: Record<string, string> = {
  delete: "Mailbox deleted",
  suspend: "Mailbox suspended",
  disable: "Mailbox disabled",
  activate: "Mailbox activated",
  block: "Sending blocked",
  restore: "Sending allowed",
  reset: "Password reset",
};

type Pending =
  | { kind: "edit" | "delete" | "suspend" | "disable" | "block" | "restore" | "reset"; mailbox: Mailbox }
  | null;

export default function Mailboxes() {
  const me = useMe();
  const [params] = useSearchParams();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [domain, setDomain] = useState(params.get("domain") ?? "");
  const [blockedOnly, setBlockedOnly] = useState(params.get("outbound_suspended") === "true");
  const business = params.get("business") ?? "";
  const term = useDebounced(search);
  const list = usePaged<Mailbox>("/mailboxes/", {
    search: term,
    status,
    domain,
    business,
    outbound_suspended: blockedOnly ? "true" : undefined,
  });
  const domains = useApiGet<Page<Domain>>("/domains/?page_size=200");
  const [creating, setCreating] = useState(params.get("new") === "1");
  const [pending, setPending] = useState<Pending>(null);
  const [reason, setReason] = useState("");
  const [password, setPassword] = useState<{ email: string; value: string } | null>(null);

  const close = () => { setPending(null); setReason(""); };
  const act = useAction(
    async ({ kind, mailbox }: { kind: string; mailbox: Mailbox }) => {
      const base = `/mailboxes/${mailbox.id}/`;
      switch (kind) {
        case "delete": await api.del(base); return null;
        case "suspend": return api.post(`${base}suspend/`, { reason });
        case "disable": return api.post(`${base}disable/`, { reason });
        case "activate": return api.post(`${base}activate/`);
        case "block": return api.post(`${base}suspend-outbound/`, { reason });
        case "restore": return api.post(`${base}restore-outbound/`, { reason });
        case "reset": {
          const r = await api.post<{ temporary_password: string }>(`${base}reset-password/`);
          setPassword({ email: mailbox.email, value: r.temporary_password });
          return null;
        }
        default: throw new Error(`Unknown action ${kind}`);
      }
    },
    { onSuccess: close, success: (_res, vars) => DONE_TEXT[vars.kind] ?? "Saved" },
  );

  const confirmCopy: Record<string, { title: (m: Mailbox) => string; body: string; action: string; danger?: boolean; reason?: boolean; typed?: boolean }> = {
    delete: { title: (m) => `Delete ${m.email}?`, body: "All mail in this mailbox is erased permanently. This cannot be undone.", action: "Delete mailbox", danger: true, typed: true },
    suspend: { title: (m) => `Suspend ${m.email}?`, body: "The user can no longer sign in or send. Incoming mail keeps arriving.", action: "Suspend mailbox", danger: true, reason: true },
    disable: { title: (m) => `Disable ${m.email}?`, body: "The mailbox stops receiving mail and nobody can sign in. Stored mail is kept.", action: "Disable mailbox", danger: true, reason: true },
    block: { title: (m) => `Block sending from ${m.email}?`, body: "Outgoing mail is blocked; the user can still read and receive mail. Only BThinkX support can lift the block.", action: "Block sending", danger: true, reason: true },
    restore: { title: (m) => `Allow sending from ${m.email}?`, body: "Make sure the password was changed and the cause of the block is resolved.", action: "Allow sending", reason: true },
    reset: { title: (m) => `Reset the password for ${m.email}?`, body: "The current password stops working immediately. Devices using it must be updated.", action: "Reset password", danger: true },
  };

  return (
    <>
      <PageHead title="Mailboxes" intro="Each mailbox is a person or team address. Users read mail in webmail or their own mail app.">
        <button className="btn primary" onClick={() => setCreating(true)}>Create mailbox</button>
      </PageHead>

      <div className="toolbar">
        <input type="search" placeholder="Search address or name" aria-label="Search mailboxes" value={search}
               onChange={(e) => setSearch(e.target.value)} />
        <select aria-label="Filter by domain" value={domain} onChange={(e) => setDomain(e.target.value)}>
          <option value="">All domains</option>
          {domains.data?.results.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </select>
        <select aria-label="Filter by status" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All statuses</option>
          <option value="ACTIVE">Active</option>
          <option value="SUSPENDED">Suspended</option>
          <option value="DISABLED">Disabled</option>
          <option value="FAILED">Failed</option>
        </select>
        <label className="check">
          <input type="checkbox" checked={blockedOnly} onChange={(e) => setBlockedOnly(e.target.checked)} />
          Sending blocked only
        </label>
      </div>

      <section className="panel">
        {list.isLoading ? (
          <Loading />
        ) : list.error ? (
          <div className="panel-body"><ErrorNotice error={list.error} /></div>
        ) : !list.data?.results.length ? (
          <Empty>
            <p>{term || status || domain || blockedOnly ? "No mailboxes match these filters." : "No mailboxes yet."}</p>
            {!term && !status && !domain && (
              <button className="btn primary" onClick={() => setCreating(true)}>Create the first mailbox</button>
            )}
          </Empty>
        ) : (
          <>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Address</th>
                    {me.is_platform_staff && <th>Business</th>}
                    <th>Status</th>
                    <th style={{ minWidth: 150 }}>Storage</th>
                    <th>Last sign-in</th>
                    <th><span className="sr-only">Actions</span></th>
                  </tr>
                </thead>
                <tbody>
                  {list.data.results.map((m) => (
                    <tr key={m.id}>
                      <td>
                        <strong className="nowrap">{m.email}</strong>
                        {m.display_name && <div className="muted small">{m.display_name}</div>}
                      </td>
                      {me.is_platform_staff && <td>{m.business_name}</td>}
                      <td>
                        <div className="actions">
                          <Badge value={m.status} />
                          {m.outbound_suspended && <Badge value="FAIL" label="Sending blocked" />}
                        </div>
                        {m.outbound_suspended && m.outbound_suspended_reason && (
                          <div className="muted small">{m.outbound_suspended_reason}</div>
                        )}
                        {m.last_error && <div className="small" style={{ color: "var(--red)" }}>{m.last_error}</div>}
                      </td>
                      <td>
                        <span className="small">{formatBytes(m.used_bytes)} of {formatMb(m.quota_mb)}</span>
                        <Meter value={m.usage_percent} max={100} />
                      </td>
                      <td className="muted small">{relative(m.last_login_at)}</td>
                      <td>
                        <select
                          aria-label={`Actions for ${m.email}`}
                          className="btn small"
                          value=""
                          onChange={(e) => {
                            const kind = e.target.value;
                            if (!kind) return;
                            if (kind === "activate") act.mutate({ kind, mailbox: m });
                            else setPending({ kind: kind as NonNullable<Pending>["kind"], mailbox: m });
                          }}
                          disabled={m.status === "PENDING" || m.status === "DELETING"}
                        >
                          <option value="">Manage…</option>
                          <option value="edit">Edit name or storage</option>
                          <option value="reset">Reset password</option>
                          {m.status !== "ACTIVE" && <option value="activate">Activate</option>}
                          {m.status === "ACTIVE" && <option value="suspend">Suspend</option>}
                          {m.status !== "DISABLED" && <option value="disable">Disable</option>}
                          {!m.outbound_suspended && <option value="block">Block sending</option>}
                          {m.outbound_suspended && me.is_platform_staff && <option value="restore">Allow sending</option>}
                          <option value="delete">Delete</option>
                        </select>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager count={list.data.count} page={list.page} pageSize={PAGE_SIZE} onPage={list.setPage} />
          </>
        )}
      </section>

      {creating && <CreateMailbox onClose={() => setCreating(false)} presetDomain={domain || undefined} />}
      {pending?.kind === "edit" && <EditMailbox mailbox={pending.mailbox} onClose={close} />}
      {pending && pending.kind !== "edit" && (() => {
        const copy = confirmCopy[pending.kind];
        if (!copy) return null;
        return (
          <Confirm
            title={copy.title(pending.mailbox)}
            action={copy.action}
            danger={copy.danger}
            confirmText={copy.typed ? pending.mailbox.email : undefined}
            busy={act.isPending}
            onClose={close}
            onConfirm={() => act.mutate({ kind: pending.kind, mailbox: pending.mailbox })}
            body={
              <div className="form">
                <p>{copy.body}</p>
                {copy.reason && (
                  <Field label="Reason (recorded in the activity log)">
                    {(fid) => <input id={fid} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={255} />}
                  </Field>
                )}
              </div>
            }
          />
        );
      })()}
      {password && (
        <Dialog title="Password reset" onClose={() => setPassword(null)}
                footer={<button className="btn primary" onClick={() => setPassword(null)}>Done</button>}>
          <SecretReveal title={`New temporary password for ${password.email}`} value={password.value} />
        </Dialog>
      )}
    </>
  );
}
