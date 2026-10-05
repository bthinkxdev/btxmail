import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { api } from "../api";
import { useMe } from "../auth";
import { Badge, Dialog, Empty, ErrorNotice, Field, Loading, PageHead, Pager } from "../components/ui";
import { formatDateTime, humanize } from "../format";
import { PAGE_SIZE, useAction, usePaged } from "../hooks";
import type { SecurityEvent } from "../types";

export default function Security() {
  const me = useMe();
  const [params] = useSearchParams();
  const [open, setOpen] = useState(params.get("open") ?? "true");
  const [severity, setSeverity] = useState("");
  const list = usePaged<SecurityEvent>("/security-events/", { open, severity });
  const [selected, setSelected] = useState<SecurityEvent | null>(null);
  const [note, setNote] = useState("");

  const resolve = useAction(
    (e: SecurityEvent) => api.post<SecurityEvent>(`/security-events/${e.id}/resolve/`, { note }),
    { success: "Event resolved", onSuccess: () => { setSelected(null); setNote(""); } },
  );

  return (
    <>
      <PageHead
        title="Security events"
        intro="Unusual sending, spam from your accounts and repeated failed logins. When sending is blocked, incoming mail still arrives."
      />
      <div className="toolbar">
        <select aria-label="Show" value={open} onChange={(e) => setOpen(e.target.value)}>
          <option value="true">Open events</option>
          <option value="false">Resolved events</option>
          <option value="">All events</option>
        </select>
        <select aria-label="Severity" value={severity} onChange={(e) => setSeverity(e.target.value)}>
          <option value="">Any severity</option>
          <option value="CRITICAL">Critical</option>
          <option value="HIGH">High</option>
          <option value="MEDIUM">Medium</option>
          <option value="LOW">Low</option>
        </select>
      </div>
      <section className="panel">
        {list.isLoading ? (
          <Loading />
        ) : list.error ? (
          <div className="panel-body"><ErrorNotice error={list.error} /></div>
        ) : !list.data?.results.length ? (
          <Empty><p>{open === "true" ? "No open security events." : "No events match."}</p></Empty>
        ) : (
          <>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Detected</th>
                    <th>Account</th>
                    {me.is_platform_staff && <th>Business</th>}
                    <th>What happened</th>
                    <th>Severity</th>
                    <th>Action taken</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {list.data.results.map((e) => (
                    <tr key={e.id}>
                      <td className="small">{formatDateTime(e.detected_at)}</td>
                      <td className="wrap-any">{e.mailbox_email ?? e.subject}</td>
                      {me.is_platform_staff && <td>{e.business_name ?? "—"}</td>}
                      <td>
                        <button className="btn link" onClick={() => setSelected(e)}>{humanize(e.event_type)}</button>
                        <div className="muted small">{e.description}</div>
                      </td>
                      <td><Badge value={e.severity} /></td>
                      <td className="small">{humanize(e.action_taken)}</td>
                      <td>{e.is_open ? <Badge value="WARN" label="Open" /> : <Badge value="OK" label="Resolved" />}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager count={list.data.count} page={list.page} pageSize={PAGE_SIZE} onPage={list.setPage} />
          </>
        )}
      </section>

      {selected && (
        <Dialog
          title={humanize(selected.event_type)}
          onClose={() => setSelected(null)}
          footer={
            me.is_platform_staff && selected.is_open ? (
              <>
                <button className="btn" onClick={() => setSelected(null)}>Close</button>
                <button className="btn primary" onClick={() => resolve.mutate(selected)} disabled={resolve.isPending}>
                  Mark resolved
                </button>
              </>
            ) : (
              <button className="btn" onClick={() => setSelected(null)}>Close</button>
            )
          }
        >
          <div className="form">
            <dl className="kv">
              <dt>Account</dt><dd>{selected.mailbox_email ?? selected.subject}</dd>
              <dt>Detected</dt><dd>{formatDateTime(selected.detected_at)}</dd>
              <dt>Details</dt><dd>{selected.description}</dd>
              {selected.message_count > 0 && (<><dt>Count</dt><dd>{selected.message_count}</dd></>)}
              {selected.source_ip && (<><dt>Source IP</dt><dd className="mono">{selected.source_ip}</dd></>)}
              <dt>Action taken</dt><dd>{humanize(selected.action_taken)}</dd>
              {selected.resolved_at && (
                <><dt>Resolved</dt><dd>{formatDateTime(selected.resolved_at)} by {selected.resolved_by_email}<br />{selected.resolution_note}</dd></>
              )}
            </dl>
            {selected.action_taken === "OUTBOUND_SUSPENDED" && selected.is_open && (
              <div className="notice warn">
                <strong>Sending is blocked for this mailbox</strong>
                Change the mailbox password, check the user's devices for malware, then ask BThinkX support to allow
                sending again.
              </div>
            )}
            {me.is_platform_staff && selected.is_open && (
              <Field label="Resolution note">
                {(id) => <textarea id={id} rows={3} value={note} onChange={(e) => setNote(e.target.value)} />}
              </Field>
            )}
          </div>
        </Dialog>
      )}
    </>
  );
}
