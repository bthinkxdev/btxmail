import { api } from "../api";
import { useMe } from "../auth";
import { Badge, Empty, ErrorNotice, Loading, PageHead } from "../components/ui";
import { plainText, relative } from "../format";
import { useAction, useApiGet } from "../hooks";
import type { Alert, Page, Reputation } from "../types";

const COMPONENT_LABEL: Record<string, string> = {
  mailcow_api: "Mail server API",
  containers: "Mail services",
  vmail_disk: "Mail storage disk",
  mail_queue: "Outgoing queue",
  tls_certificate: "TLS certificate",
  backup: "Last backup",
};

export default function System() {
  const me = useMe();
  const rep = useApiGet<Reputation>("/monitoring/reputation/", { refetchInterval: 60_000 });
  const alerts = useApiGet<Page<Alert>>("/monitoring/alerts/?open=true&page_size=50");
  const run = useAction((job: string) => api.post(`/monitoring/run/`, { job }), {
    success: (_r, job) => `Started: ${job}. Results appear here in a minute.`,
  });
  const ack = useAction((id: number) => api.post(`/monitoring/alerts/${id}/acknowledge/`), { success: "Alert acknowledged" });

  if (rep.isLoading) return <Loading />;
  if (rep.error || !rep.data) return <ErrorNotice error={rep.error} />;
  const r = rep.data;

  return (
    <>
      <PageHead title="Mail server health" intro={`${r.mail_hostname} · ${r.mail_ip || "IP not configured"}`}>
        {me.is_super_admin && (
          <>
            <button className="btn" onClick={() => run.mutate("health")} disabled={run.isPending}>Check health now</button>
            <button className="btn" onClick={() => run.mutate("blacklists")} disabled={run.isPending}>Check blacklists</button>
            <button className="btn" onClick={() => run.mutate("sync")} disabled={run.isPending}>Sync mailboxes</button>
          </>
        )}
      </PageHead>

      {r.status === "LISTED" && (
        <div className="notice bad">
          <strong>The mail IP is on a blacklist</strong>
          Mail to some providers will be rejected. Find the sending source in Security events, stop it, then request
          delisting from each list.
        </div>
      )}

      <div className="two-col">
        <section className="panel">
          <div className="panel-head"><h2>Components</h2></div>
          {Object.keys(r.components).length === 0 ? (
            <Empty><p>No health checks have run yet. They run every five minutes once the worker is up.</p></Empty>
          ) : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>Component</th><th>Status</th><th>Detail</th><th>Checked</th></tr></thead>
                <tbody>
                  {Object.entries(r.components).map(([name, c]) => (
                    <tr key={name}>
                      <td>{COMPONENT_LABEL[name] ?? name}</td>
                      <td><Badge value={c.status} /></td>
                      <td className="small">{plainText(c.message)}</td>
                      <td className="muted small">{relative(c.checked_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="panel">
          <div className="panel-head">
            <h2>Blacklists</h2>
            <Badge value={r.status} />
          </div>
          {r.blacklists.length === 0 ? (
            <Empty><p>Not checked yet.</p></Empty>
          ) : (
            <div className="table-wrap">
              <table>
                <tbody>
                  {r.blacklists.map((b) => (
                    <tr key={b.zone}>
                      <td className="small">{b.zone}</td>
                      <td>
                        {b.error ? <Badge value="UNKNOWN" label="Could not check" /> : <Badge value={b.listed ? "LISTED" : "OK"} label={b.listed ? "Listed" : "Clean"} />}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>

      <section className="panel" style={{ marginTop: 20 }}>
        <div className="panel-head"><h2>Open alerts</h2></div>
        {!alerts.data?.results.length ? (
          <Empty><p>No open alerts.</p></Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Raised</th><th>Severity</th><th>Alert</th><th>Delivered</th><th><span className="sr-only">Actions</span></th></tr></thead>
              <tbody>
                {alerts.data.results.map((a) => (
                  <tr key={a.id}>
                    <td className="muted small">{relative(a.created_at)}</td>
                    <td><Badge value={a.severity} /></td>
                    <td><strong>{plainText(a.title)}</strong><div className="small muted" style={{ whiteSpace: "pre-line" }}>{plainText(a.message)}</div></td>
                    <td className="small">{a.delivered ? "Yes" : a.delivery_error ? "Failed" : "Pending"}</td>
                    <td><button className="btn small" onClick={() => ack.mutate(a.id)} disabled={ack.isPending}>Acknowledge</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
