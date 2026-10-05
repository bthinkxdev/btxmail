import { Link } from "react-router-dom";

import { useMe } from "../auth";
import { Badge, Empty, ErrorNotice, Loading, Meter, PageHead } from "../components/ui";
import { formatBytes, formatMb, humanize, relative } from "../format";
import { useApiGet } from "../hooks";
import type { Dashboard as DashboardData } from "../types";

export default function Dashboard() {
  const me = useMe();
  const { data, isLoading, error } = useApiGet<DashboardData>("/dashboard/");
  if (isLoading) return <Loading />;
  if (error || !data) return <ErrorNotice error={error} />;

  const biz = data.business;
  const pendingDomains = data.domains.pending;

  return (
    <>
      <PageHead
        title={biz ? biz.name : "Platform overview"}
        intro={
          biz
            ? `${biz.plan.name} plan. Manage your domains, mailboxes and forwarding here; people read their mail in webmail.`
            : "Every business, domain and mailbox on the BThinkX mail platform."
        }
      >
        <Link className="btn" to="/domains">
          Add domain
        </Link>
        <Link className="btn primary" to="/mailboxes?new=1">
          Create mailbox
        </Link>
      </PageHead>

      {pendingDomains > 0 && (
        <div className="notice info">
          <strong>
            {pendingDomains === 1 ? "1 domain is" : `${pendingDomains} domains are`} not live yet
          </strong>
          Open the domain to see which DNS records still need to be published.
        </div>
      )}

      <div className="summary">
        {data.businesses && (
          <div>
            <div className="k">Businesses</div>
            <div className="v">
              {data.businesses.active} <small>active · {data.businesses.suspended} suspended</small>
            </div>
          </div>
        )}
        <div>
          <div className="k">Domains</div>
          <div className="v">
            {data.domains.total}
            {biz && <small> / {biz.limits.domains}</small>}
          </div>
          {biz && <Meter value={data.domains.total} max={biz.limits.domains} />}
        </div>
        <div>
          <div className="k">Mailboxes</div>
          <div className="v">
            {data.mailboxes.total}
            {biz && <small> / {biz.limits.mailboxes}</small>}
          </div>
          {biz && <Meter value={data.mailboxes.total} max={biz.limits.mailboxes} />}
        </div>
        <div>
          <div className="k">Storage allocated</div>
          <div className="v">
            {formatMb(data.storage.allocated_mb)}
            {biz && <small> / {formatMb(biz.limits.storage_mb)}</small>}
          </div>
          {biz && <Meter value={data.storage.allocated_mb} max={biz.limits.storage_mb} />}
        </div>
        <div>
          <div className="k">Storage used</div>
          <div className="v">{formatBytes(data.storage.used_bytes)}</div>
        </div>
      </div>

      <div className="two-col">
        <section className="panel">
          <div className="panel-head">
            <h2>Open security events</h2>
            <Link to="/security?open=true" className="small">
              View all ({data.open_security_events})
            </Link>
          </div>
          {data.recent_security_events.length === 0 ? (
            <Empty>
              <p>No open security events. Unusual sending or repeated failed logins will appear here.</p>
            </Empty>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Mailbox</th>
                    <th>What happened</th>
                    <th>Severity</th>
                    <th>Action taken</th>
                    <th>When</th>
                  </tr>
                </thead>
                <tbody>
                  {data.recent_security_events.map((e) => (
                    <tr key={e.id}>
                      <td className="nowrap">{e.subject}</td>
                      <td>{e.description || humanize(e.event_type)}</td>
                      <td>
                        <Badge value={e.severity} />
                      </td>
                      <td>{humanize(e.action_taken)}</td>
                      <td className="muted">{relative(e.detected_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="panel">
          <div className="panel-head">
            <h2>Mailboxes</h2>
          </div>
          <div className="panel-body">
            <dl className="kv">
              <dt>Active</dt>
              <dd>{data.mailboxes.active}</dd>
              <dt>Suspended</dt>
              <dd>{data.mailboxes.suspended}</dd>
              <dt>Sending blocked</dt>
              <dd>
                {data.mailboxes.outbound_suspended > 0 ? (
                  <Link to="/mailboxes?outbound_suspended=true">{data.mailboxes.outbound_suspended}</Link>
                ) : (
                  0
                )}
              </dd>
              {biz && (
                <>
                  <dt>Forwarding addresses</dt>
                  <dd>
                    {biz.aliases} / {biz.limits.aliases}
                  </dd>
                  <dt>Status</dt>
                  <dd>
                    <Badge value={biz.status} />
                  </dd>
                </>
              )}
              {me.is_platform_staff && (
                <>
                  <dt>Mail server</dt>
                  <dd>
                    <Link to="/system">Health and reputation</Link>
                  </dd>
                </>
              )}
            </dl>
          </div>
        </section>
      </div>
    </>
  );
}
