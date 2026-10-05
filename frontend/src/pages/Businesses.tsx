import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api, ApiError } from "../api";
import { Badge, Dialog, Empty, ErrorNotice, Field, Loading, PageHead, Pager } from "../components/ui";
import { formatBytes, formatDate } from "../format";
import { PAGE_SIZE, useAction, useApiGet, useDebounced, usePaged } from "../hooks";
import type { Business, Page, Plan } from "../types";

export interface BusinessForm {
  name: string;
  legal_name: string;
  contact_person: string;
  contact_email: string;
  contact_phone: string;
  plan: number | "";
  notes: string;
}

export function BusinessFields({ value, onChange, plans, error }: {
  value: BusinessForm;
  onChange: (v: BusinessForm) => void;
  plans: Plan[];
  error: ApiError | null;
}) {
  const set = (k: keyof BusinessForm) => (e: { target: { value: string } }) =>
    onChange({ ...value, [k]: k === "plan" ? (e.target.value ? Number(e.target.value) : "") : e.target.value });
  return (
    <>
      <div className="form-row">
        <Field label="Business name" error={error?.field("name")}>
          {(id) => <input id={id} value={value.name} onChange={set("name")} required maxLength={200} />}
        </Field>
        <Field label="Legal name" error={error?.field("legal_name")}>
          {(id) => <input id={id} value={value.legal_name} onChange={set("legal_name")} maxLength={255} />}
        </Field>
      </div>
      <div className="form-row">
        <Field label="Contact person">
          {(id) => <input id={id} value={value.contact_person} onChange={set("contact_person")} maxLength={200} />}
        </Field>
        <Field label="Contact phone" error={error?.field("contact_phone")}>
          {(id) => <input id={id} type="tel" value={value.contact_phone} onChange={set("contact_phone")} maxLength={32} />}
        </Field>
      </div>
      <Field label="Contact e-mail" hint="Billing and service notices go here." error={error?.field("contact_email")}>
        {(id) => <input id={id} type="email" value={value.contact_email} onChange={set("contact_email")} required />}
      </Field>
      <Field label="Plan" error={error?.field("plan")}>
        {(id) => (
          <select id={id} value={value.plan} onChange={set("plan")} required>
            <option value="">Choose a plan</option>
            {plans.filter((p) => p.is_active).map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} — {p.max_mailboxes} mailboxes, {p.max_domains} domains
              </option>
            ))}
          </select>
        )}
      </Field>
      <Field label="Internal notes" hint="Visible to BThinkX staff only.">
        {(id) => <textarea id={id} rows={3} value={value.notes} onChange={set("notes")} />}
      </Field>
    </>
  );
}

export const EMPTY_BUSINESS: BusinessForm = {
  name: "",
  legal_name: "",
  contact_person: "",
  contact_email: "",
  contact_phone: "",
  plan: "",
  notes: "",
};

export default function Businesses() {
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const term = useDebounced(search);
  const list = usePaged<Business>("/businesses/", { search: term, status });
  const plans = useApiGet<Page<Plan>>("/plans/?page_size=200");
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState<BusinessForm>(EMPTY_BUSINESS);

  const create = useAction((body: BusinessForm) => api.post<Business>("/businesses/", body), {
    success: (b) => `Business ${b.name} created`,
    onSuccess: (b) => navigate(`/businesses/${b.id}`),
  });
  const createError = create.error instanceof ApiError ? create.error : null;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate(form);
  };

  return (
    <>
      <PageHead title="Businesses" intro="Customer accounts. Each business owns its domains, mailboxes and admins.">
        <button className="btn primary" onClick={() => { setForm(EMPTY_BUSINESS); create.reset(); setCreating(true); }}>
          Create business
        </button>
      </PageHead>

      <div className="toolbar">
        <input type="search" placeholder="Search by name or e-mail" aria-label="Search businesses" value={search}
               onChange={(e) => setSearch(e.target.value)} />
        <select aria-label="Filter by status" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All statuses</option>
          <option value="ACTIVE">Active</option>
          <option value="SUSPENDED">Suspended</option>
          <option value="CLOSED">Closed</option>
        </select>
      </div>

      <section className="panel">
        {list.isLoading ? (
          <Loading />
        ) : list.error ? (
          <div className="panel-body"><ErrorNotice error={list.error} /></div>
        ) : !list.data?.results.length ? (
          <Empty>
            <p>{term || status ? "No businesses match these filters." : "No businesses yet. Create the first customer account."}</p>
          </Empty>
        ) : (
          <>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Business</th>
                    <th>Plan</th>
                    <th>Status</th>
                    <th className="num">Domains</th>
                    <th className="num">Mailboxes</th>
                    <th className="num">Storage used</th>
                    <th>Since</th>
                  </tr>
                </thead>
                <tbody>
                  {list.data.results.map((b) => (
                    <tr key={b.id}>
                      <td>
                        <Link to={`/businesses/${b.id}`}>{b.name}</Link>
                        <div className="muted small">{b.contact_email}</div>
                      </td>
                      <td>{b.plan_detail.name}</td>
                      <td><Badge value={b.status} /></td>
                      <td className="num">{b.usage.domains}</td>
                      <td className="num">{b.usage.mailboxes} / {b.plan_detail.max_mailboxes}</td>
                      <td className="num">{formatBytes(b.usage.used_storage_bytes)}</td>
                      <td className="muted">{formatDate(b.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager count={list.data.count} page={list.page} pageSize={PAGE_SIZE} onPage={list.setPage} />
          </>
        )}
      </section>

      {creating && (
        <Dialog
          title="Create business"
          onClose={() => setCreating(false)}
          footer={
            <>
              <button className="btn" onClick={() => setCreating(false)}>Cancel</button>
              <button className="btn primary" form="biz-create" disabled={create.isPending}>
                {create.isPending ? "Creating…" : "Create business"}
              </button>
            </>
          }
        >
          <form id="biz-create" className="form" onSubmit={submit}>
            <BusinessFields value={form} onChange={setForm} plans={plans.data?.results ?? []} error={createError} />
          </form>
        </Dialog>
      )}
    </>
  );
}
