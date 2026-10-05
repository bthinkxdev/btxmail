import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { api, ApiError } from "../api";
import { useMe } from "../auth";
import { Badge, Dialog, Empty, ErrorNotice, Field, Loading, PageHead, Pager } from "../components/ui";
import { relative } from "../format";
import { PAGE_SIZE, useAction, useApiGet, useDebounced, usePaged } from "../hooks";
import type { Business, Domain, Page } from "../types";

export function BusinessSelect({ value, onChange, error, allowAll }: {
  value: string;
  onChange: (v: string) => void;
  error?: string;
  allowAll?: boolean;
}) {
  const businesses = useApiGet<Page<Business>>("/businesses/?page_size=200&status=ACTIVE");
  return (
    <Field label="Business" error={error}>
      {(id) => (
        <select id={id} value={value} onChange={(e) => onChange(e.target.value)}>
          <option value="">{allowAll ? "All businesses" : "Choose a business"}</option>
          {businesses.data?.results.map((b) => (
            <option key={b.id} value={b.id}>{b.name}</option>
          ))}
        </select>
      )}
    </Field>
  );
}

export default function Domains() {
  const me = useMe();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const presetBusiness = params.get("business") ?? "";
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [businessFilter, setBusinessFilter] = useState(presetBusiness);
  const term = useDebounced(search);
  const list = usePaged<Domain>("/domains/", { search: term, status, business: businessFilter });

  const [adding, setAdding] = useState(Boolean(presetBusiness));
  const [name, setName] = useState("");
  const [business, setBusiness] = useState(presetBusiness);

  const create = useAction(
    (body: { name: string; business?: number }) => api.post<Domain>("/domains/", body),
    { success: (d) => `${d.name} added — publish the verification record next`, onSuccess: (d) => navigate(`/domains/${d.id}`) },
  );
  const err = create.error instanceof ApiError ? create.error : null;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate({ name, ...(me.is_platform_staff ? { business: Number(business) || undefined } : {}) });
  };

  return (
    <>
      <PageHead
        title="Domains"
        intro="A domain goes live in three steps: prove you own it, publish the mail records, and we confirm them."
      >
        <button className="btn primary" onClick={() => { create.reset(); setName(""); setAdding(true); }}>
          Add domain
        </button>
      </PageHead>

      <div className="toolbar">
        <input type="search" placeholder="Search domains" aria-label="Search domains" value={search}
               onChange={(e) => setSearch(e.target.value)} />
        <select aria-label="Filter by status" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All statuses</option>
          <option value="PENDING_VERIFICATION">Awaiting verification</option>
          <option value="DNS_PENDING">Awaiting DNS</option>
          <option value="ACTIVE">Active</option>
          <option value="PROVISIONING_FAILED">Setup failed</option>
          <option value="SUSPENDED">Suspended</option>
        </select>
        {me.is_platform_staff && businessFilter && (
          <button className="btn small" onClick={() => setBusinessFilter("")}>Show all businesses</button>
        )}
      </div>

      <section className="panel">
        {list.isLoading ? (
          <Loading />
        ) : list.error ? (
          <div className="panel-body"><ErrorNotice error={list.error} /></div>
        ) : !list.data?.results.length ? (
          <Empty>
            <p>{term || status ? "No domains match these filters." : "No domains yet. Add the domain your team sends mail from, such as yourcompany.com."}</p>
          </Empty>
        ) : (
          <>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Domain</th>
                    {me.is_platform_staff && <th>Business</th>}
                    <th>Status</th>
                    <th className="num">Mailboxes</th>
                    <th className="num">Forwarding</th>
                    <th>DNS checked</th>
                  </tr>
                </thead>
                <tbody>
                  {list.data.results.map((d) => (
                    <tr key={d.id}>
                      <td><Link to={`/domains/${d.id}`}>{d.name}</Link></td>
                      {me.is_platform_staff && <td>{d.business_name}</td>}
                      <td><Badge value={d.status} /></td>
                      <td className="num">{d.mailbox_count}</td>
                      <td className="num">{d.alias_count}</td>
                      <td className="muted">{relative(d.dns_status?.last_checked)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager count={list.data.count} page={list.page} pageSize={PAGE_SIZE} onPage={list.setPage} />
          </>
        )}
      </section>

      {adding && (
        <Dialog
          title="Add domain"
          onClose={() => setAdding(false)}
          footer={
            <>
              <button className="btn" onClick={() => setAdding(false)}>Cancel</button>
              <button className="btn primary" form="domain-add" disabled={create.isPending || !name}>
                {create.isPending ? "Adding…" : "Add domain"}
              </button>
            </>
          }
        >
          <form id="domain-add" className="form" onSubmit={submit}>
            {err && !err.errors && <div className="notice bad">{err.message}</div>}
            {me.is_platform_staff && (
              <BusinessSelect value={business} onChange={setBusiness} error={err?.field("business")} />
            )}
            <Field label="Domain name" hint="Without www or http — for example abctraders.com." error={err?.field("name")}>
              {(id) => (
                <input id={id} value={name} onChange={(e) => setName(e.target.value)} placeholder="yourcompany.com"
                       autoComplete="off" spellCheck={false} required />
              )}
            </Field>
          </form>
        </Dialog>
      )}
    </>
  );
}
