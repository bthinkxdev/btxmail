import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api } from "../api";
import { useMe } from "../auth";
import { Badge, Confirm, CopyButton, ErrorNotice, Field, Loading, PageHead } from "../components/ui";
import { formatDateTime, relative } from "../format";
import { useAction, useApiGet } from "../hooks";
import type { CheckStatus, DnsCheckDetail, DnsRecord, Domain } from "../types";

const STAMP_TEXT: Record<CheckStatus, string> = {
  PASS: "PASSED",
  FAIL: "NOT YET",
  WARN: "REVIEW",
  UNKNOWN: "WAITING",
};

function Postmark({ status, when, fresh }: { status: CheckStatus; when?: string | null; fresh: boolean }) {
  const d = when ? new Date(when) : null;
  const sub = d ? d.toLocaleDateString(undefined, { day: "2-digit", month: "short" }).toUpperCase() : "";
  return (
    <div className={`postmark ${status}${fresh ? " fresh" : ""}`} role="img" aria-label={`Check result: ${STAMP_TEXT[status]}`}>
      <span>
        {STAMP_TEXT[status]}
        {sub && <span className="pm-sub">{sub}</span>}
      </span>
    </div>
  );
}

function RecordRows({ record }: { record: DnsRecord }) {
  return (
    <dl className="record">
      <dt>Type</dt>
      <dd>
        <code>{record.type}</code>
      </dd>
      <dt>Name / host</dt>
      <dd>
        <code>{record.name}</code>
        <CopyButton value={record.name} />
      </dd>
      {record.priority !== undefined && (
        <>
          <dt>Priority</dt>
          <dd>
            <code>{record.priority}</code>
          </dd>
        </>
      )}
      <dt>Value</dt>
      <dd>
        <code>{record.value}</code>
        <CopyButton value={record.value} />
      </dd>
    </dl>
  );
}

function Found({ detail }: { detail?: DnsCheckDetail }) {
  if (!detail) return null;
  return (
    <div className="found">
      {detail.message}
      {detail.found.length > 0 && (
        <>
          {" "}Currently published: <code className="wrap-any">{detail.found.join(" | ")}</code>
        </>
      )}
    </div>
  );
}

export default function DomainDetail() {
  const { id } = useParams();
  const me = useMe();
  const navigate = useNavigate();
  const [freshStamps, setFreshStamps] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [manual, setManual] = useState(false);
  const [manualReason, setManualReason] = useState("");

  const query = useApiGet<Domain>(`/domains/${id}/`, {
    // poll while the mail server is being set up
    refetchInterval: (q) => (q.state.data?.status === "PROVISIONING" ? 4000 : false),
  });

  useEffect(() => {
    if (!freshStamps) return;
    const t = window.setTimeout(() => setFreshStamps(false), 900);
    return () => window.clearTimeout(t);
  }, [freshStamps]);

  const verify = useAction(
    () => api.post<{ result: DnsCheckDetail; domain: Domain }>(`/domains/${id}/verify/`),
    {
      success: (r) => (r.result.status === "PASS" ? "Ownership verified — setting up mail" : "Verification record not found yet"),
      onSuccess: () => setFreshStamps(true),
    },
  );
  const check = useAction(() => api.post<Domain>(`/domains/${id}/check-dns/`), {
    success: (d) => (d.status === "ACTIVE" ? "All required records found — domain is live" : "DNS checked"),
    onSuccess: () => setFreshStamps(true),
  });
  const regenerate = useAction(() => api.post<Domain>(`/domains/${id}/regenerate-token/`), {
    success: "New verification value created",
  });
  const retry = useAction(() => api.post<Domain>(`/domains/${id}/retry-provisioning/`), { success: "Setup restarted" });
  const suspend = useAction(() => api.post<Domain>(`/domains/${id}/suspend/`), { success: "Domain suspended" });
  const activate = useAction(() => api.post<Domain>(`/domains/${id}/activate/`), { success: "Domain reactivated" });
  const manualVerify = useAction(
    () => api.post<Domain>(`/domains/${id}/verify-manually/`, { reason: manualReason }),
    { success: "Marked as verified", onSuccess: () => setManual(false) },
  );
  const remove = useAction(() => api.del(`/domains/${id}/`), {
    success: "Domain deleted",
    onSuccess: () => navigate("/domains", { replace: true }),
  });

  if (query.isLoading) return <Loading />;
  if (query.error || !query.data) return <ErrorNotice error={query.error} />;
  const d = query.data;
  const dns = d.dns_status;
  const rec = (p: DnsRecord["purpose"]) => d.dns_records.find((r) => r.purpose === p);
  const pendingVerification = d.status === "PENDING_VERIFICATION";
  const verifyStatus: CheckStatus = d.verified_at ? "PASS" : d.verification.last_attempt_at ? "FAIL" : "UNKNOWN";
  const checked = dns?.last_checked;
  const waitingForSetup = !d.mailcow_provisioned;
  const stampFor = (s?: CheckStatus): CheckStatus => (waitingForSetup ? "UNKNOWN" : (s ?? "UNKNOWN"));

  return (
    <>
      <PageHead
        crumb={<Link className="crumb" to="/domains">Domains</Link>}
        title={d.name}
        intro={
          <>
            <Badge value={d.status} /> {me.is_platform_staff && <>· {d.business_name} </>}
            {d.mailbox_count > 0 && <>· <Link to={`/mailboxes?domain=${d.id}`}>{d.mailbox_count} mailboxes</Link></>}
          </>
        }
      >
        {pendingVerification ? (
          <button className="btn primary" onClick={() => verify.mutate()} disabled={verify.isPending}>
            {verify.isPending ? "Checking…" : "Check verification record"}
          </button>
        ) : d.mailcow_provisioned ? (
          <button className="btn primary" onClick={() => check.mutate()} disabled={check.isPending}>
            {check.isPending ? "Checking DNS…" : "Check DNS now"}
          </button>
        ) : null}
        {me.is_platform_staff && d.mailcow_provisioned && d.status !== "SUSPENDED" && (
          <button className="btn danger" onClick={() => suspend.mutate()} disabled={suspend.isPending}>Suspend</button>
        )}
        {me.is_platform_staff && d.status === "SUSPENDED" && (
          <button className="btn" onClick={() => activate.mutate()} disabled={activate.isPending}>Reactivate</button>
        )}
        <button className="btn danger" onClick={() => setConfirmDelete(true)}>Delete</button>
      </PageHead>

      {d.status === "PROVISIONING" && (
        <div className="notice info" aria-live="polite">
          <strong>Setting up {d.name} on the mail server</strong>
          This normally takes under a minute. The DNS records below appear when it is done.
        </div>
      )}
      {d.status === "PROVISIONING_FAILED" && (
        <div className="notice bad">
          <strong>Mail server setup failed</strong>
          {me.is_platform_staff ? d.last_error : "BThinkX support has been alerted and will retry."}
          {me.is_platform_staff && (
            <div className="actions" style={{ marginTop: 8 }}>
              <button className="btn small" onClick={() => retry.mutate()} disabled={retry.isPending}>Retry setup</button>
            </div>
          )}
        </div>
      )}
      {d.status === "ACTIVE" && (
        <div className="notice ok">
          <strong>{d.name} is live</strong>
          Mail for this domain is delivered to BThinkX. We re-check the records every 30 minutes and alert you if
          one breaks.
        </div>
      )}
      {d.status === "SUSPENDED" && (
        <div className="notice bad">
          <strong>Domain suspended</strong>
          Contact BThinkX support to restore service.
        </div>
      )}

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Setup slip</h2>
            <p className="muted small">
              Add these records at your DNS provider (Cloudflare, GoDaddy, BigRock…). Changes can take up to an hour
              to be visible. Last checked {relative(checked)}.
            </p>
          </div>
        </div>
        <ol className="slip">
          <li>
            <div>
              <h3>Prove you own the domain</h3>
              <p className="why">
                A one-time TXT record shows us you control {d.name}. Nothing else changes until this passes.
              </p>
              {d.verified_at ? (
                <p className="found">
                  Verified {formatDateTime(d.verified_at)}
                  {d.verification_method === "MANUAL" && " by BThinkX staff"}. You may remove this record now.
                </p>
              ) : (
                <>
                  {rec("VERIFICATION") && <RecordRows record={rec("VERIFICATION") as DnsRecord} />}
                  <div className="actions" style={{ marginTop: 10 }}>
                    <button className="btn small" onClick={() => regenerate.mutate()} disabled={regenerate.isPending}>
                      Create a new value
                    </button>
                    {me.is_platform_staff && (
                      <button className="btn small" onClick={() => setManual(true)}>Verify manually</button>
                    )}
                  </div>
                </>
              )}
            </div>
            <Postmark status={verifyStatus} when={d.verified_at ?? d.verification.last_attempt_at} fresh={freshStamps} />
          </li>

          <li>
            <div>
              <h3>Route incoming mail to BThinkX</h3>
              <p className="why">
                The MX record tells other mail servers where to deliver mail for {d.name}. Remove MX records that
                point to your previous provider.
              </p>
              {rec("MX") && <RecordRows record={rec("MX") as DnsRecord} />}
              {!waitingForSetup && <Found detail={dns?.details.mx} />}
            </div>
            <Postmark status={stampFor(dns?.mx_status)} when={checked} fresh={freshStamps} />
          </li>

          <li>
            <div>
              <h3>Authorise BThinkX to send for you</h3>
              <p className="why">
                SPF lists the servers allowed to send as @{d.name}. Keep exactly one SPF record; if you already have
                one, add <code>mx</code> to it instead of creating a second.
              </p>
              {rec("SPF") && <RecordRows record={rec("SPF") as DnsRecord} />}
              {!waitingForSetup && <Found detail={dns?.details.spf} />}
            </div>
            <Postmark status={stampFor(dns?.spf_status)} when={checked} fresh={freshStamps} />
          </li>

          <li>
            <div>
              <h3>Publish the signing key</h3>
              <p className="why">
                DKIM signs every message so Gmail and Outlook can tell it really came from you.
              </p>
              {rec("DKIM") ? (
                <RecordRows record={rec("DKIM") as DnsRecord} />
              ) : (
                <p className="found">The key is generated once ownership is verified.</p>
              )}
              {!waitingForSetup && <Found detail={dns?.details.dkim} />}
            </div>
            <Postmark status={stampFor(dns?.dkim_status)} when={checked} fresh={freshStamps} />
          </li>

          <li>
            <div>
              <h3>Set a DMARC policy (recommended)</h3>
              <p className="why">
                DMARC tells receivers what to do with mail that fails SPF and DKIM — it stops others spoofing{" "}
                {d.name}. Optional for going live, strongly advised.
              </p>
              {rec("DMARC") && <RecordRows record={rec("DMARC") as DnsRecord} />}
              {!waitingForSetup && <Found detail={dns?.details.dmarc} />}
            </div>
            <Postmark status={stampFor(dns?.dmarc_status)} when={checked} fresh={freshStamps} />
          </li>
        </ol>
      </section>

      <section className="panel">
        <div className="panel-head"><h2>Easy setup for mail apps (optional)</h2></div>
        <div className="panel-body form">
          <p className="small muted">
            These let Outlook, Thunderbird and phones find the right settings automatically.
          </p>
          {rec("AUTODISCOVER") && <RecordRows record={rec("AUTODISCOVER") as DnsRecord} />}
          {rec("AUTOCONFIG") && <RecordRows record={rec("AUTOCONFIG") as DnsRecord} />}
          {me.is_platform_staff && dns && (
            <p className="small">
              Platform reverse DNS (PTR): <Badge value={dns.ptr_status} /> <span className="muted">{dns.details.ptr?.message}</span>
            </p>
          )}
        </div>
      </section>

      {confirmDelete && (
        <Confirm
          title={`Delete ${d.name}?`}
          danger
          action="Delete domain"
          confirmText={d.name}
          busy={remove.isPending}
          onClose={() => setConfirmDelete(false)}
          onConfirm={() => remove.mutate()}
          body={
            d.mailbox_count + d.alias_count > 0 ? (
              <div className="notice warn">
                Delete its {d.mailbox_count} mailboxes and {d.alias_count} forwarding addresses first. Deleting a
                mailbox erases its mail.
              </div>
            ) : (
              <p>The domain is removed from the mail server. Mail sent to it will bounce.</p>
            )
          }
        />
      )}

      {manual && (
        <Confirm
          title="Verify ownership manually"
          action="Mark as verified"
          busy={manualVerify.isPending}
          onClose={() => setManual(false)}
          onConfirm={() => manualVerify.mutate()}
          body={
            <div className="form">
              <p>Only do this after confirming ownership another way. It is recorded in the activity log.</p>
              <Field label="How was ownership confirmed?">
                {(fid) => <input id={fid} value={manualReason} onChange={(e) => setManualReason(e.target.value)} maxLength={500} />}
              </Field>
            </div>
          }
        />
      )}
    </>
  );
}
