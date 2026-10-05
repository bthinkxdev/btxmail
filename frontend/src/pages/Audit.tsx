import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { useMe } from "../auth";
import { Empty, ErrorNotice, Loading, PageHead, Pager } from "../components/ui";
import { formatDateTime } from "../format";
import { PAGE_SIZE, useDebounced, usePaged } from "../hooks";
import type { AuditEntry } from "../types";

const ACTION_TEXT: Record<string, string> = {
  "auth.login": "Signed in",
  "auth.logout": "Signed out",
  "auth.login_failed": "Failed sign-in",
  "auth.otp_failed": "Wrong authentication code",
  "auth.login_blocked": "Sign-in blocked (locked)",
  "auth.password_changed": "Changed own password",
  "auth.password_reset_requested": "Requested password reset",
  "auth.password_reset_completed": "Reset password by e-mail",
  "auth.2fa_enabled": "Turned on two-factor authentication",
  "auth.2fa_disabled": "Turned off two-factor authentication",
  "auth.recovery_codes_regenerated": "Generated new recovery codes",
  "business.created": "Created business",
  "business.updated": "Updated business",
  "business.status_changed": "Changed business status",
  "domain.created": "Added domain",
  "domain.verified": "Verified domain ownership",
  "domain.verified_manually": "Verified domain manually",
  "domain.provisioned": "Set up domain on mail server",
  "domain.provisioning_failed": "Domain setup failed",
  "domain.provisioning_retried": "Retried domain setup",
  "domain.activated": "Domain went live",
  "domain.suspended": "Suspended domain",
  "domain.reactivated": "Reactivated domain",
  "domain.deleted": "Deleted domain",
  "domain.token_regenerated": "New verification value",
  "mailbox.created": "Created mailbox",
  "mailbox.updated": "Updated mailbox",
  "mailbox.suspended": "Suspended mailbox",
  "mailbox.disabled": "Disabled mailbox",
  "mailbox.activated": "Activated mailbox",
  "mailbox.password_reset": "Reset mailbox password",
  "mailbox.outbound_suspended": "Blocked sending",
  "mailbox.outbound_restored": "Allowed sending",
  "mailbox.deleted": "Deleted mailbox",
  "alias.created": "Created forwarding address",
  "alias.updated": "Updated forwarding address",
  "alias.deleted": "Deleted forwarding address",
  "user.created": "Created portal user",
  "user.updated": "Updated portal user",
  "user.deleted": "Deleted portal user",
  "user.password_reset": "Reset portal user password",
  "user.2fa_reset": "Reset portal user two-factor",
  "sync.drift_corrected": "Corrected a change made outside the portal",
  "sync.mailbox_missing": "Mailbox missing on mail server",
  "sync.mailbox_imported": "Imported mailbox created outside the portal",
  "security_event.resolved": "Resolved security event",
};

function describeMeta(entry: AuditEntry): string {
  const m = entry.metadata;
  const parts: string[] = [];
  for (const key of ["email", "domain", "address", "reason", "note", "role", "quota_mb", "from", "to"]) {
    const v = m[key];
    if (v !== undefined && v !== "" && v !== null) parts.push(`${key.replace("_", " ")}: ${String(v)}`);
  }
  return parts.join(" · ");
}

export default function Audit() {
  const me = useMe();
  const [params] = useSearchParams();
  const [search, setSearch] = useState("");
  const [actor, setActor] = useState("");
  const [action, setAction] = useState("");
  const term = useDebounced(search);
  const actorTerm = useDebounced(actor);
  const list = usePaged<AuditEntry>("/audit-logs/", {
    search: term,
    actor: actorTerm,
    action,
    business: params.get("business") ?? undefined,
  });

  return (
    <>
      <PageHead title="Activity log" intro="Every change made through the portal, who made it and from where. Kept for two years." />
      <div className="toolbar">
        <input type="search" placeholder="Search by object (e.g. sales@)" aria-label="Search activity" value={search}
               onChange={(e) => setSearch(e.target.value)} />
        <input type="search" placeholder="Filter by person" aria-label="Filter by person" value={actor}
               onChange={(e) => setActor(e.target.value)} />
        <select aria-label="Filter by area" value={action} onChange={(e) => setAction(e.target.value)}>
          <option value="">All activity</option>
          <option value="auth.">Sign-ins and accounts</option>
          <option value="domain.">Domains</option>
          <option value="mailbox.">Mailboxes</option>
          <option value="alias.">Forwarding</option>
          <option value="user.">Portal users</option>
          {me.is_platform_staff && <option value="business.">Businesses</option>}
          {me.is_platform_staff && <option value="sync.">Mail server sync</option>}
        </select>
      </div>
      <section className="panel">
        {list.isLoading ? (
          <Loading />
        ) : list.error ? (
          <div className="panel-body"><ErrorNotice error={list.error} /></div>
        ) : !list.data?.results.length ? (
          <Empty><p>No activity matches these filters.</p></Empty>
        ) : (
          <>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>When</th>
                    <th>Who</th>
                    <th>What</th>
                    <th>Object</th>
                    {me.is_platform_staff && <th>Business</th>}
                    <th>IP address</th>
                  </tr>
                </thead>
                <tbody>
                  {list.data.results.map((e) => (
                    <tr key={e.id}>
                      <td className="small" style={{ whiteSpace: "nowrap" }}>{formatDateTime(e.timestamp)}</td>
                      <td className="wrap-any small">{e.actor_email || <span className="muted">System</span>}</td>
                      <td>
                        {ACTION_TEXT[e.action] ?? e.action}
                        {describeMeta(e) && <div className="muted small wrap-any">{describeMeta(e)}</div>}
                      </td>
                      <td className="wrap-any small">{e.object_repr || "—"}</td>
                      {me.is_platform_staff && <td className="small">{e.business_name ?? "—"}</td>}
                      <td className="mono small">{e.ip_address ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager count={list.data.count} page={list.page} pageSize={PAGE_SIZE} onPage={list.setPage} />
          </>
        )}
      </section>
    </>
  );
}
