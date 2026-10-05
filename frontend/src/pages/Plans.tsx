import { useState, type FormEvent } from "react";

import { api, ApiError } from "../api";
import { useMe } from "../auth";
import { Badge, Dialog, Empty, ErrorNotice, Field, Loading, PageHead } from "../components/ui";
import { formatMb } from "../format";
import { useAction, useApiGet } from "../hooks";
import type { Page, Plan } from "../types";

type PlanForm = Omit<Plan, "id">;

const BLANK: PlanForm = {
  code: "",
  name: "",
  description: "",
  max_domains: 3,
  max_mailboxes: 10,
  max_aliases: 50,
  default_mailbox_quota_mb: 5120,
  max_mailbox_quota_mb: 5120,
  total_storage_mb: 51200,
  outbound_per_hour: 100,
  outbound_per_day: 500,
  is_active: true,
};

const NUMBER_FIELDS: [keyof PlanForm, string, string?][] = [
  ["max_domains", "Domains"],
  ["max_mailboxes", "Mailboxes"],
  ["max_aliases", "Forwarding addresses"],
  ["default_mailbox_quota_mb", "Default mailbox size (MB)"],
  ["max_mailbox_quota_mb", "Largest mailbox (MB)"],
  ["total_storage_mb", "Total storage (MB)", "Sum of all mailbox sizes."],
  ["outbound_per_hour", "Sending limit per hour", "Per mailbox; enforced by the mail server."],
  ["outbound_per_day", "Sending limit per day", "Per mailbox; exceeding it blocks sending."],
];

function PlanDialog({ plan, onClose }: { plan?: Plan; onClose: () => void }) {
  const [form, setForm] = useState<PlanForm>(plan ? { ...plan } : BLANK);
  const save = useAction(
    (body: PlanForm) => (plan ? api.patch<Plan>(`/plans/${plan.id}/`, body) : api.post<Plan>("/plans/", body)),
    { success: (p) => `Plan ${p.name} saved`, onSuccess: onClose },
  );
  const err = save.error instanceof ApiError ? save.error : null;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate(form);
  };
  return (
    <Dialog
      title={plan ? `Edit ${plan.name}` : "Create plan"}
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" form="plan-form" disabled={save.isPending}>
            {save.isPending ? "Saving…" : "Save plan"}
          </button>
        </>
      }
    >
      <form id="plan-form" className="form" onSubmit={submit}>
        {err && !err.errors && <div className="notice bad">{err.message}</div>}
        {plan && (
          <div className="notice info small">Changes apply to every business on this plan and are pushed to the mail server.</div>
        )}
        <div className="form-row">
          <Field label="Name" error={err?.field("name")}>
            {(id) => <input id={id} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />}
          </Field>
          <Field label="Code" hint="Short identifier, e.g. business-plus" error={err?.field("code")}>
            {(id) => <input id={id} value={form.code} pattern="[-a-zA-Z0-9_]+" onChange={(e) => setForm({ ...form, code: e.target.value })} required />}
          </Field>
        </div>
        <Field label="Description">
          {(id) => <input id={id} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />}
        </Field>
        <div className="form-row">
          {NUMBER_FIELDS.map(([key, label, hint]) => (
            <Field key={key} label={label} hint={hint} error={err?.field(key)}>
              {(id) => (
                <input id={id} type="number" min={1} value={form[key] as number}
                       onChange={(e) => setForm({ ...form, [key]: Number(e.target.value) })} required />
              )}
            </Field>
          ))}
        </div>
        <label className="check">
          <input type="checkbox" checked={form.is_active}
                 onChange={(e) => setForm({ ...form, is_active: e.target.checked })} />
          Available for new businesses
        </label>
      </form>
    </Dialog>
  );
}

export default function Plans() {
  const me = useMe();
  const plans = useApiGet<Page<Plan>>("/plans/?page_size=200");
  const [editing, setEditing] = useState<Plan | "new" | null>(null);
  return (
    <>
      <PageHead title="Plans" intro="Limits applied to each business. Changing a plan updates every business on it.">
        {me.is_super_admin && <button className="btn primary" onClick={() => setEditing("new")}>Create plan</button>}
      </PageHead>
      <section className="panel">
        {plans.isLoading ? (
          <Loading />
        ) : plans.error ? (
          <div className="panel-body"><ErrorNotice error={plans.error} /></div>
        ) : !plans.data?.results.length ? (
          <Empty><p>No plans yet.</p></Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Plan</th>
                  <th className="num">Domains</th>
                  <th className="num">Mailboxes</th>
                  <th className="num">Per mailbox</th>
                  <th className="num">Total storage</th>
                  <th className="num">Sending / hour</th>
                  <th className="num">Sending / day</th>
                  <th>Status</th>
                  <th><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {plans.data.results.map((p) => (
                  <tr key={p.id}>
                    <td><strong>{p.name}</strong><div className="muted small">{p.description}</div></td>
                    <td className="num">{p.max_domains}</td>
                    <td className="num">{p.max_mailboxes}</td>
                    <td className="num">{formatMb(p.max_mailbox_quota_mb)}</td>
                    <td className="num">{formatMb(p.total_storage_mb)}</td>
                    <td className="num">{p.outbound_per_hour}</td>
                    <td className="num">{p.outbound_per_day}</td>
                    <td><Badge value={p.is_active ? "OK" : "DISABLED"} label={p.is_active ? "Available" : "Retired"} /></td>
                    <td>{me.is_super_admin && <button className="btn small" onClick={() => setEditing(p)}>Edit</button>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {editing && <PlanDialog plan={editing === "new" ? undefined : editing} onClose={() => setEditing(null)} />}
    </>
  );
}
