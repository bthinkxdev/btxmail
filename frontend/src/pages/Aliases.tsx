import { useState, type FormEvent } from "react";

import { api, ApiError } from "../api";
import { useMe } from "../auth";
import { Badge, Confirm, Dialog, Empty, ErrorNotice, Field, Loading, PageHead, Pager } from "../components/ui";
import { PAGE_SIZE, useAction, useApiGet, useDebounced, usePaged } from "../hooks";
import type { Alias, Domain, Page } from "../types";

function parseDestinations(text: string): string[] {
  return text.split(/[\s,;]+/).map((s) => s.trim()).filter(Boolean);
}

function AliasDialog({ alias, onClose }: { alias?: Alias; onClose: () => void }) {
  const domainsQ = useApiGet<Page<Domain>>("/domains/?page_size=200");
  const domains = (domainsQ.data?.results ?? []).filter((d) => d.mailcow_provisioned && d.status !== "SUSPENDED");
  const [domain, setDomain] = useState("");
  const [local, setLocal] = useState("");
  const [dests, setDests] = useState(alias ? alias.destinations.join("\n") : "");
  const domainId = domain || (domains.length === 1 ? String(domains[0]?.id) : "");
  const chosen = domains.find((d) => String(d.id) === domainId);

  const save = useAction(
    (body: Record<string, unknown>) =>
      alias ? api.patch<Alias>(`/aliases/${alias.id}/`, body) : api.post<Alias>("/aliases/", body),
    { success: (a) => (alias ? "Forwarding saved" : `${a.source_address} created`), onSuccess: onClose },
  );
  const err = save.error instanceof ApiError ? save.error : null;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const destinations = parseDestinations(dests);
    save.mutate(alias ? { destinations } : { domain: Number(domainId), local_part: local, destinations });
  };

  return (
    <Dialog
      title={alias ? `Edit ${alias.source_address}` : "Create forwarding address"}
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" form="alias-form" disabled={save.isPending}>
            {save.isPending ? "Saving…" : alias ? "Save changes" : "Create forwarding address"}
          </button>
        </>
      }
    >
      <form id="alias-form" className="form" onSubmit={submit}>
        {err && !err.errors && <div className="notice bad">{err.message}</div>}
        {!alias && (
          <>
            {domains.length > 1 && (
              <Field label="Domain">
                {(id) => (
                  <select id={id} value={domainId} onChange={(e) => setDomain(e.target.value)} required>
                    <option value="">Choose a domain</option>
                    {domains.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
                  </select>
                )}
              </Field>
            )}
            <Field label="Address" hint="Mail sent here is passed on; it has no inbox of its own." error={err?.field("local_part")}>
              {(id) => (
                <div className="input-suffix">
                  <input id={id} value={local} onChange={(e) => setLocal(e.target.value.toLowerCase())} placeholder="hello"
                         required maxLength={64} autoComplete="off" spellCheck={false} />
                  <span>@{chosen?.name ?? "domain"}</span>
                </div>
              )}
            </Field>
          </>
        )}
        <Field label="Deliver to" hint="One address per line. Up to 20." error={err?.field("destinations")}>
          {(id) => <textarea id={id} rows={4} value={dests} onChange={(e) => setDests(e.target.value)}
                             placeholder={"info@yourcompany.com\nowner@gmail.com"} required spellCheck={false} />}
        </Field>
      </form>
    </Dialog>
  );
}

export default function Aliases() {
  const me = useMe();
  const [search, setSearch] = useState("");
  const term = useDebounced(search);
  const list = usePaged<Alias>("/aliases/", { search: term });
  const [editing, setEditing] = useState<Alias | "new" | null>(null);
  const [deleting, setDeleting] = useState<Alias | null>(null);

  const toggle = useAction(
    (a: Alias) => api.patch<Alias>(`/aliases/${a.id}/`, { status: a.status === "ACTIVE" ? "DISABLED" : "ACTIVE" }),
    { success: (a) => (a.status === "ACTIVE" ? "Forwarding turned on" : "Forwarding paused") },
  );
  const remove = useAction((a: Alias) => api.del(`/aliases/${a.id}/`), {
    success: "Forwarding address deleted",
    onSuccess: () => setDeleting(null),
  });

  return (
    <>
      <PageHead title="Forwarding" intro="Addresses like hello@ or support@ that pass mail on to one or more mailboxes.">
        <button className="btn primary" onClick={() => setEditing("new")}>Create forwarding address</button>
      </PageHead>
      <div className="toolbar">
        <input type="search" placeholder="Search addresses" aria-label="Search forwarding addresses" value={search}
               onChange={(e) => setSearch(e.target.value)} />
      </div>
      <section className="panel">
        {list.isLoading ? (
          <Loading />
        ) : list.error ? (
          <div className="panel-body"><ErrorNotice error={list.error} /></div>
        ) : !list.data?.results.length ? (
          <Empty><p>{term ? "No forwarding addresses match." : "No forwarding addresses yet."}</p></Empty>
        ) : (
          <>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Address</th>
                    {me.is_platform_staff && <th>Business</th>}
                    <th>Delivers to</th>
                    <th>Status</th>
                    <th><span className="sr-only">Actions</span></th>
                  </tr>
                </thead>
                <tbody>
                  {list.data.results.map((a) => (
                    <tr key={a.id}>
                      <td><strong className="nowrap">{a.source_address}</strong></td>
                      {me.is_platform_staff && <td>{a.business_name}</td>}
                      <td className="wrap-any small">{a.destinations.join(", ")}</td>
                      <td><Badge value={a.status} label={a.status === "ACTIVE" ? "On" : "Paused"} /></td>
                      <td>
                        <div className="actions">
                          <button className="btn small" onClick={() => setEditing(a)}>Edit</button>
                          <button className="btn small" onClick={() => toggle.mutate(a)} disabled={toggle.isPending}>
                            {a.status === "ACTIVE" ? "Pause" : "Turn on"}
                          </button>
                          <button className="btn small danger" onClick={() => setDeleting(a)}>Delete</button>
                        </div>
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
      {editing && <AliasDialog alias={editing === "new" ? undefined : editing} onClose={() => setEditing(null)} />}
      {deleting && (
        <Confirm
          title={`Delete ${deleting.source_address}?`}
          danger
          action="Delete forwarding address"
          busy={remove.isPending}
          onClose={() => setDeleting(null)}
          onConfirm={() => remove.mutate(deleting)}
          body={<p>Mail sent to this address will bounce. The destination mailboxes are not affected.</p>}
        />
      )}
    </>
  );
}
