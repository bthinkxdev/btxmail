import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";

import { api, ApiError } from "../api";
import { Badge, Confirm, Dialog, Empty, ErrorNotice, Field, Loading, Meter, PageHead } from "../components/ui";
import { formatBytes, formatDate, formatMb } from "../format";
import { useAction, useApiGet } from "../hooks";
import type { Business, Domain, Page, Plan } from "../types";
import { BusinessFields, type BusinessForm } from "./Businesses";

export default function BusinessDetail() {
  const { id } = useParams();
  const business = useApiGet<Business>(`/businesses/${id}/`);
  const domains = useApiGet<Page<Domain>>(`/businesses/${id}/domains/`);
  const plans = useApiGet<Page<Plan>>("/plans/?page_size=200");
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<BusinessForm | null>(null);
  const [suspending, setSuspending] = useState(false);
  const [reason, setReason] = useState("");

  const save = useAction((body: BusinessForm) => api.patch<Business>(`/businesses/${id}/`, body), {
    success: "Business saved",
    onSuccess: () => setEditing(false),
  });
  const suspend = useAction(() => api.post<Business>(`/businesses/${id}/suspend/`, { reason }), {
    success: "Business suspended",
    onSuccess: () => setSuspending(false),
  });
  const activate = useAction(() => api.post<Business>(`/businesses/${id}/activate/`), { success: "Business reactivated" });

  if (business.isLoading) return <Loading />;
  if (business.error || !business.data) return <ErrorNotice error={business.error} />;
  const b = business.data;
  const plan = b.plan_detail;

  const openEdit = () => {
    save.reset();
    setForm({
      name: b.name,
      legal_name: b.legal_name,
      contact_person: b.contact_person,
      contact_email: b.contact_email,
      contact_phone: b.contact_phone,
      plan: b.plan,
      notes: b.notes,
    });
    setEditing(true);
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (form) save.mutate(form);
  };

  return (
    <>
      <PageHead
        crumb={<Link className="crumb" to="/businesses">Businesses</Link>}
        title={b.name}
        intro={b.legal_name || undefined}
      >
        <button className="btn" onClick={openEdit}>Edit details</button>
        {b.status === "ACTIVE" ? (
          <button className="btn danger" onClick={() => { setReason(""); setSuspending(true); }}>
            Suspend business
          </button>
        ) : (
          <button className="btn primary" onClick={() => activate.mutate()} disabled={activate.isPending}>
            Reactivate business
          </button>
        )}
      </PageHead>

      {b.status !== "ACTIVE" && (
        <div className="notice bad">
          <strong>This business is {b.status.toLowerCase()}</strong>
          Mail is still delivered to its mailboxes, but nobody can sign in to webmail or send.
          {b.suspended_reason && <> Reason: {b.suspended_reason}</>}
        </div>
      )}

      <div className="summary">
        <div>
          <div className="k">Domains</div>
          <div className="v">{b.usage.domains} <small>/ {plan.max_domains}</small></div>
          <Meter value={b.usage.domains} max={plan.max_domains} />
        </div>
        <div>
          <div className="k">Mailboxes</div>
          <div className="v">{b.usage.mailboxes} <small>/ {plan.max_mailboxes}</small></div>
          <Meter value={b.usage.mailboxes} max={plan.max_mailboxes} />
        </div>
        <div>
          <div className="k">Storage allocated</div>
          <div className="v">{formatMb(b.usage.allocated_storage_mb)} <small>/ {formatMb(plan.total_storage_mb)}</small></div>
          <Meter value={b.usage.allocated_storage_mb} max={plan.total_storage_mb} />
        </div>
        <div>
          <div className="k">Storage used</div>
          <div className="v">{formatBytes(b.usage.used_storage_bytes)}</div>
        </div>
      </div>

      <div className="two-col">
        <section className="panel">
          <div className="panel-head">
            <h2>Domains</h2>
            <Link className="btn small" to={`/domains?business=${b.id}`}>Add domain</Link>
          </div>
          {domains.isLoading ? (
            <Loading />
          ) : !domains.data?.results.length ? (
            <Empty><p>No domains yet.</p></Empty>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr><th>Domain</th><th>Status</th><th className="num">Mailboxes</th></tr>
                </thead>
                <tbody>
                  {domains.data.results.map((d) => (
                    <tr key={d.id}>
                      <td><Link to={`/domains/${d.id}`}>{d.name}</Link></td>
                      <td><Badge value={d.status} /></td>
                      <td className="num">{d.mailbox_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="panel">
          <div className="panel-head"><h2>Account</h2></div>
          <div className="panel-body">
            <dl className="kv">
              <dt>Status</dt><dd><Badge value={b.status} /></dd>
              <dt>Plan</dt><dd>{plan.name}</dd>
              <dt>Per mailbox</dt><dd>up to {formatMb(plan.max_mailbox_quota_mb)}</dd>
              <dt>Sending limit</dt><dd>{plan.outbound_per_hour}/hour, {plan.outbound_per_day}/day per mailbox</dd>
              <dt>Contact</dt><dd>{b.contact_person || "—"}<br />{b.contact_email}<br />{b.contact_phone}</dd>
              <dt>Customer since</dt><dd>{formatDate(b.created_at)}</dd>
              {b.notes && (<><dt>Notes</dt><dd>{b.notes}</dd></>)}
            </dl>
            <div className="actions" style={{ marginTop: 16 }}>
              <Link className="btn small" to={`/mailboxes?business=${b.id}`}>Mailboxes</Link>
              <Link className="btn small" to={`/users?business=${b.id}`}>Admins</Link>
              <Link className="btn small" to={`/audit?business=${b.id}`}>Activity</Link>
            </div>
          </div>
        </section>
      </div>

      {editing && form && (
        <Dialog
          title="Edit business"
          onClose={() => setEditing(false)}
          footer={
            <>
              <button className="btn" onClick={() => setEditing(false)}>Cancel</button>
              <button className="btn primary" form="biz-edit" disabled={save.isPending}>
                {save.isPending ? "Saving…" : "Save changes"}
              </button>
            </>
          }
        >
          <form id="biz-edit" className="form" onSubmit={submit}>
            {save.error instanceof ApiError && !save.error.errors && (
              <div className="notice bad">{save.error.message}</div>
            )}
            <BusinessFields value={form} onChange={setForm} plans={plans.data?.results ?? []}
                            error={save.error instanceof ApiError ? save.error : null} />
          </form>
        </Dialog>
      )}

      {suspending && (
        <Confirm
          title={`Suspend ${b.name}?`}
          danger
          action="Suspend business"
          confirmText={b.name}
          busy={suspend.isPending}
          onClose={() => setSuspending(false)}
          onConfirm={() => suspend.mutate()}
          body={
            <div className="form">
              <p>All {b.usage.mailboxes} mailboxes will be blocked from signing in and sending. Incoming mail keeps arriving, and nothing is deleted.</p>
              <Field label="Reason (shown to staff)">
                {(fid) => <input id={fid} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={255} />}
              </Field>
            </div>
          }
        />
      )}
    </>
  );
}
