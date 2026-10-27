# BThinkX Business Email Platform

A multi-tenant control plane for selling and operating business email.
**Django owns the customer relationship; Mailcow owns the mail infrastructure.**

BThinkX staff create businesses, customers add and verify their own domains, and admins issue mailboxes,
forwarding addresses and limits from one portal. Mail itself (SMTP, IMAP, webmail, spam and virus
filtering, storage) runs on Mailcow, which the portal drives through its API and watches continuously.

```text
                    Customers / BThinkX staff                     Mailbox users
                               │                                       │
                     https://portal.bthinkx.com              https://mail.bthinkx.com/SOGo
                               │                              IMAP / SMTP / ActiveSync
 ┌─────────────── APP SERVER ──┼──────────────────────┐               │
 │  nginx (TLS, CSP, rate limits) ── React portal      │               │
 │        │                                            │               │
 │  Django REST API ── PostgreSQL                      │               │
 │        │   └──── Redis ── Celery worker + beat      │               │
 │        │               (provisioning, DNS checks,   │               │
 │        │                sync, abuse, health)        │               │
 └────────┼────────────────────────────────────────────┘               │
          │ Mailcow REST API (IP-restricted, API key)                  │
 ┌────────▼──────────── MAIL SERVER ───────────────────────────────────▼─┐
 │  Mailcow: Postfix · Dovecot · SOGo · Rspamd · ClamAV · MariaDB · Redis │
 └───────────────────────────┬──────────────────────────────────────────┘
                             │ nightly, encrypted (age) → offsite object storage
```

---

## Contents

1. [What is included](#1-what-is-included)
2. [Repository layout](#2-repository-layout)
3. [Run it locally](#3-run-it-locally)
4. [Deploy to production](#4-deploy-to-production)
5. [Configuration](#5-configuration)
6. [How it works](#6-how-it-works)
7. [Security model](#7-security-model)
8. [API reference](#8-api-reference)
9. [Operations runbook](#9-operations-runbook)
10. [Testing](#10-testing)
11. [Known limitations and pre-launch checks](#11-known-limitations-and-pre-launch-checks)

---

## 1. What is included

| Area | Delivered |
| --- | --- |
| Businesses & plans | Businesses with contact details and status; plans with limits for domains, mailboxes, aliases, per-mailbox and total storage, hourly and daily sending. Plan changes are validated (no downgrade below current usage) and pushed to Mailcow. |
| Domains | Ownership verification by DNS TXT (`_bthinkx-verification.<domain>`), staff manual override, automatic Mailcow provisioning with DKIM, a per-domain DNS checklist (MX, SPF, DKIM, DMARC, PTR) re-checked every 30 minutes, regression alerts, suspend/reactivate, safe deletion. |
| Mailboxes | Create (temporary password shown once, forced change at first login), edit name and quota, suspend (login blocked, mail still delivered), disable, activate, reset password, delete. Quotas enforced per mailbox, per business and per plan. |
| Forwarding | Aliases with up to 20 destinations, pause/resume, conflict checks against mailboxes. |
| Abuse protection | Per-mailbox Mailcow rate limit from the plan; detector reading Rspamd history, rate-limit and Dovecot logs every 5 minutes; automatic **outbound-only** suspension (incoming mail continues); security events and alerts. Only BThinkX staff can lift a block. |
| Sync | Every 5 minutes: usage and last-login import, drift correction (Django's desired state is re-applied), missing-mailbox detection, import of mailboxes created directly in Mailcow. |
| Monitoring | Mailcow API and container health, mail storage disk, outgoing queue, TLS expiry, DNS blacklists, backup freshness; alerts by e-mail and webhook with de-duplication; Prometheus metrics; optional Prometheus/Grafana/Loki stack. |
| Security | Session auth with CSRF, mandatory TOTP 2FA with recovery codes and replay protection, lockout, throttling, RBAC (super admin / operations admin / business admin), strict tenant isolation, full audit log, encrypted TOTP secrets, security headers and CSP. |
| Portal | React + TypeScript SPA: overview, businesses, domains with a step-by-step setup slip, mailboxes, forwarding, security events, activity log, portal users, plans, mail-server health, account settings. Responsive and keyboard accessible. |
| Installable app (PWA) | The portal installs to the home screen / desktop (Android, iOS, Windows, macOS, ChromeOS) with its own icon, standalone window, safe-area support and shortcuts to Mailboxes, Domains and Forwarding. The app shell works offline with an offline notice; an in-app bar offers updates. API responses are never cached, so no business data is stored on the device. |
| Operations | Docker images, Compose stack, nginx edge with TLS bootstrap and Let's Encrypt renewal, encrypted offsite backups for Mailcow and the app DB, restore script, Mailcow setup guide, CI workflow. |

**Deliberately not built in V1** (per the brief): a custom webmail client, mobile app, calendar/drive, newsletters or marketing mail, billing integration, a custom SMTP server. Mailbox users use SOGo webmail or any IMAP/SMTP/ActiveSync client.

---

## 2. Repository layout

```text
bthinkx-mail/
├── backend/                     Django 5.2 + DRF control plane
│   ├── config/                  settings (all env-driven), urls, celery, test settings
│   ├── apps/
│   │   ├── core/                request IDs, errors, health/metrics, crypto, bootstrap commands
│   │   ├── accounts/            users, roles, login + TOTP, lockout, RBAC + tenancy helpers
│   │   ├── businesses/          plans, businesses, dashboard
│   │   ├── domains/             domain lifecycle, DNS checks, provisioning tasks
│   │   ├── mailboxes/           mailboxes, aliases, sync tasks
│   │   ├── mailcow/             the ONLY code that talks to Mailcow (client, domains, mailboxes,
│   │   │                        aliases, dkim, health, logs, error mapping)
│   │   ├── security/            security events, abuse detection
│   │   ├── monitoring/          health checks, blacklists, backup heartbeat
│   │   ├── notifications/       alerts (e-mail / webhook, de-duplicated)
│   │   └── audit/               append-only audit log
│   ├── tests/                   pytest suite with a stateful fake Mailcow and fake DNS
│   ├── docker/entrypoint.sh     web | worker | beat | manage
│   └── Dockerfile
├── frontend/                    React 19 + TypeScript + Vite portal
│   ├── src/                     pages, components, API client
│   ├── nginx/                   edge config (TLS, CSP, rate limits, SPA + API proxy)
│   └── Dockerfile               builds the SPA into the nginx edge image
├── deploy/
│   ├── mailcow/                 mail server guide + encrypted backup job
│   ├── scripts/                 app DB backup/restore, certificate issuance
│   └── monitoring/              Prometheus, Grafana, Loki overlay
├── docker-compose.yml           app server stack
├── .env.example                 every setting, documented
├── Makefile
└── .github/workflows/ci.yml
```

---

## 3. Run it locally

Requirements: Python 3.12+, Node 22+. No Docker, Postgres or Redis needed for development (SQLite, in-memory cache and eager Celery are used automatically when `DJANGO_DEBUG=1`).

```bash
# Backend
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements/dev.txt
export DJANGO_DEBUG=1 CELERY_TASK_ALWAYS_EAGER=1
export BOOTSTRAP_ADMIN_EMAIL=you@example.com BOOTSTRAP_ADMIN_PASSWORD='Change-Me-Locally-1'
python manage.py migrate && python manage.py bootstrap
python manage.py runserver 127.0.0.1:8000

# Frontend (second terminal)
cd frontend
npm install
npm run dev          # http://localhost:5173 — proxies /api to :8000
```

Sign in with the bootstrap account; you will be asked to change the password and enrol an authenticator app. To develop against a real Mailcow, also export `MAILCOW_API_URL` and `MAILCOW_API_KEY`; without them, mail-server actions return a clear "temporarily unavailable" error and raise an alert.

---

## 4. Deploy to production

Three machines, as recommended in the brief:

| Server | Runs | Suggested size |
| --- | --- | --- |
| SERVER 1 — app | this repository's Compose stack | 2 vCPU, 4 GB RAM, 40 GB |
| SERVER 2 — mail | Mailcow only | 4+ vCPU, 16 GB RAM, 200–500 GB NVMe, dedicated clean IPv4 |
| SERVER 3 / object storage | encrypted offsite backups | Backblaze B2, Wasabi, S3 … |

### 4.1 Mail server

Follow **[deploy/mailcow/README.md](deploy/mailcow/README.md)**: DNS and PTR, Mailcow install, `API_KEY` and `API_ALLOW_FROM=<app server IP>` in `mailcow.conf`, firewall, hardening and the backup job.

### 4.2 App server

```bash
# Ubuntu 24.04
curl -fsSL https://get.docker.com | sh
git clone <this repository> /opt/bthinkx-mail && cd /opt/bthinkx-mail

cp .env.example .env && chmod 600 .env
# Fill every CHANGE_ME:
#   openssl rand -base64 48        → DJANGO_SECRET_KEY, POSTGRES_PASSWORD, REDIS_PASSWORD, BACKUP_REPORT_TOKEN
#   python3 -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"  → FIELD_ENCRYPTION_KEY
#   MAILCOW_API_KEY = the API_KEY from mailcow.conf

# DNS: A portal.bthinkx.com → this server
docker compose up -d --build
deploy/scripts/issue-certificate.sh admin@bthinkx.com      # Let's Encrypt + auto-renewal
docker compose exec backend python manage.py check_mailcow  # must list all containers "running"
```

Open `https://portal.bthinkx.com`, sign in as `BOOTSTRAP_ADMIN_EMAIL`, change the password, enrol 2FA and **store the recovery codes**. Then remove `BOOTSTRAP_ADMIN_PASSWORD` from `.env` and run `docker compose up -d`.

Firewall the app server to 22 (admin IPs) and 80/443 only. Postgres and Redis are on an internal Docker network and are never published.

### 4.3 Backups for the app database

```bash
# once: install age + rclone, configure the rclone remote, put the age PUBLIC key in /etc/bthinkx/backup-recipients.txt
echo '15 1 * * * root cd /opt/bthinkx-mail && deploy/scripts/backup-app-db.sh >> /var/log/bthinkx-db-backup.log 2>&1' \
  > /etc/cron.d/bthinkx-db-backup
```

Restore (also the weekly restore test): `deploy/scripts/restore-app-db.sh <dump.sql.gz.age> <age-private-key>`.

### 4.4 Monitoring (optional overlay)

```bash
echo 'GRAFANA_ADMIN_PASSWORD=<strong password>' >> .env
docker compose -f docker-compose.yml -f deploy/monitoring/docker-compose.monitoring.yml up -d
ssh -L 3000:127.0.0.1:3000 app-server     # Grafana at http://localhost:3000
```

The portal's own **Mail server health** page and alert e-mails work without this overlay.

### 4.5 Updating

```bash
git pull && docker compose up -d --build     # migrations run automatically on the web container
```

---

## 5. Configuration

Every setting is an environment variable; `.env.example` documents each one. The ones that matter most:

| Variable | Purpose |
| --- | --- |
| `DJANGO_SECRET_KEY`, `FIELD_ENCRYPTION_KEY` | Required in production; the app refuses to start without them. The Fernet key encrypts TOTP secrets at rest — keep a copy, losing it forces every admin to re-enrol 2FA. |
| `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `PORTAL_URL` | The portal hostname. |
| `MAILCOW_API_URL`, `MAILCOW_API_KEY`, `MAILCOW_VERIFY_TLS` | Mail server API access. |
| `MAIL_HOSTNAME`, `MAIL_IPV4` | What customer MX records must point to; used by MX/SPF/PTR checks and blacklist monitoring. |
| `SPF_RECORD`, `DMARC_RECORD`, `DKIM_SELECTOR`, `DKIM_KEY_SIZE` | Records shown to customers. |
| `ENFORCE_2FA` | Default on. All portal users must enrol TOTP before using the API. |
| `ABUSE_*` | Thresholds for automatic outbound suspension. |
| `EMAIL_*` | SMTP for portal mail (password resets, alerts). **Use a separate transactional provider**, not the Mailcow IP, so portal mail cannot damage mailbox reputation (brief §28). |
| `ALERT_EMAILS`, `ALERT_WEBHOOK_URL` | Where operational alerts go. |
| `BACKUP_REPORT_TOKEN`, `BACKUP_MAX_AGE_HOURS` | Backup heartbeat from the mail server. |
| `NUM_PROXIES` | Proxies in front of Django: 1 for nginx, 2 if nginx is behind Cloudflare. Determines the client IP used for lockout and audit. |
| `ADMIN_URL` | Django admin path; empty (default) disables it. It has no 2FA — use only as break-glass, with an unguessable path. |

---

## 6. How it works

### Domain lifecycle

```text
PENDING_VERIFICATION ──TXT found──▶ PROVISIONING ──Mailcow domain + DKIM──▶ DNS_PENDING ──MX+SPF+DKIM pass──▶ ACTIVE
        │  (or staff "verify manually")      │                                      ▲
        │                         3 retries failed (30s, 2m, 10m)                   │ re-checked every 30 min;
        ▼                                    ▼                                      │ alert if a record breaks
  token expires after 14 days       PROVISIONING_FAILED ──staff retry──────────────┘
```

Nothing is created in Mailcow until ownership is proven. Mailboxes can be created once the domain is provisioned (`DNS_PENDING`), so customers can migrate before switching MX; the portal warns that external mail only arrives once MX is live.

### Mailbox provisioning without half-created objects

Each mutation locks the business row (so concurrent requests cannot both pass a quota check), validates plan limits, calls Mailcow, then commits. If anything fails after Mailcow accepted the change — e.g. the rate-limit call or the database commit — the remote mailbox is deleted again (compensation). If even that fails, a critical "orphaned mailbox" alert is raised and the next sync imports it for review. Mailbox passwords are generated server-side, sent to Mailcow, returned to the admin once with `Cache-Control: no-store`, and never stored or logged by the platform.

### Desired state and sync

Django is authoritative for **business decisions** (is this mailbox active, suspended, allowed to send, how big). Mailcow is authoritative for **mail facts** (usage, message count, last login, existence). Every 5 minutes the sync job imports the facts and re-applies the decisions if someone changed them directly in Mailcow, recording each correction in the audit log.

| Portal state | Mailcow `active` | Effect |
| --- | --- | --- |
| Active | `1` | Normal |
| Suspended, or business suspended | `2` | Cannot sign in or send; **mail still delivered** |
| Disabled | `0` | Mailbox off |
| Sending blocked (any state) | `smtp_access=0` | Cannot send; can read and receive |

### Abuse detection

Each mailbox gets a Mailcow rate limit of its plan's hourly limit (enforced by Mailcow itself). Every 5 minutes the detector reads the last `ABUSE_LOG_LOOKBACK` entries of Rspamd history, the rate-limit log and the Dovecot log:

| Signal | Rule (defaults) | Action |
| --- | --- | --- |
| Outbound volume | > hourly limit × 3 in the last hour, or > daily limit in 24 h | `HIGH_OUTBOUND_VOLUME`, sending blocked |
| Outbound spam | ≥ 10 outbound messages rejected/flagged by Rspamd in an hour | `SPAM_ACTIVITY`, sending blocked |
| Rate limit hits | any in the last hour (≥ 50 → block) | `RATE_LIMITED` |
| Failed logins | ≥ 20 in an hour (≤ 3 IPs → brute force) | `LOGIN_BRUTE_FORCE` / `AUTH_FAILURE`, alert (Mailcow's netfilter bans IPs) |

Events are de-duplicated per mailbox per hour. If the detector cannot read Mailcow logs, it alerts rather than failing silently.

### Scheduled jobs (Celery beat)

| Job | Every |
| --- | --- |
| Verify pending domains | 5 min |
| Sync Mailcow | 5 min |
| Detect abuse | 5 min |
| Mail server health (API, containers, disk, queue, TLS) | 5 min |
| Re-queue stuck provisioning | 15 min |
| DNS checks for provisioned domains | 30 min |
| Blacklist check | 1 h |
| Backup freshness | 6 h |
| Prune old health/alert/audit records | daily (audit kept 730 days) |

Super admins can trigger health, blacklist, sync, abuse and DNS jobs immediately from **Mail server health**.

---

## 7. Security model

**Roles**

| | Super admin | Operations admin | Business admin |
| --- | --- | --- | --- |
| Businesses, plans | all; edit plans | all; cannot edit plans | own business (read) |
| Domains, mailboxes, aliases | all | all | own business only |
| Lift a sending block, resolve security events, manual domain verification, suspend domains | ✓ | ✓ | — |
| Change mailbox sending limits | ✓ | ✓ | — |
| Create portal users | any role | business admins | business admins in own business |
| Trigger jobs, reset other users' 2FA | ✓ (2FA reset: staff) | 2FA reset | — |

**Tenant isolation.** The business a request acts on is always derived from the signed-in user. A `business` id from the client is only honoured for staff; business admins' ids are ignored. Every queryset passes through one scoping helper, and objects outside the tenant return 404 (not 403) so their existence is not revealed. The test suite attacks this directly (reading, editing, deleting and creating on another tenant's objects).

**Authentication.** Session cookies (`HttpOnly`, `Secure`, `SameSite=Lax`) with CSRF tokens on every write; same-origin SPA, CORS closed by default. TOTP 2FA is mandatory (`ENFORCE_2FA=1`): until a user has changed a temporary password and enrolled 2FA, the API answers only account-setup endpoints. Codes are single-use per 30-second step; 10 one-time recovery codes are stored as SHA-256 hashes; TOTP seeds are Fernet-encrypted. Lockout after 5 failures per e-mail (20 per IP) for 15 minutes, plus DRF throttles and nginx `limit_req` on login. Password reset uses Django's signed, single-use, one-hour tokens and never reveals whether an account exists. Passwords: minimum 12 characters, common and numeric passwords rejected.

**Transport and browser.** HTTPS only (HSTS one year), strict CSP (`script-src 'self'`), `X-Frame-Options: DENY`, `nosniff`, referrer and permissions policies, request IDs end to end. `/metrics` and `/readyz` are not reachable through nginx.

**Mailcow access.** Only the backend calls Mailcow — never the browser. The API key lives in the server environment; Mailcow additionally restricts the API to the app server's IP.

**Audit.** Every sensitive action is written with actor, role, business, object, IP, user agent, request ID and metadata (secrets scrubbed). Business admins see their own business's log; staff see everything.

---

## 8. API reference

All endpoints are under `/api/`, JSON in and out, session auth + `X-CSRFToken` header on writes. Lists are paginated (`?page=`, `?page_size=` ≤ 200) and accept the filters noted. Errors look like `{"detail": "...", "code": "...", "errors": {field: [...]}, "request_id": "..."}`.

| Method & path | Notes |
| --- | --- |
| `GET auth/csrf/` | Sets the CSRF cookie |
| `POST auth/login/` · `POST auth/login/otp/` | Returns `{"status":"otp_required"}` when 2FA is on |
| `POST auth/logout/` · `GET auth/me/` | `me.setup_required` tells the SPA what is pending |
| `POST auth/password/change/` · `auth/password/reset/` · `auth/password/reset/confirm/` | |
| `POST auth/2fa/setup/` · `auth/2fa/enable/` · `auth/2fa/disable/` · `auth/2fa/recovery-codes/` | Disable is refused while 2FA is enforced |
| `GET dashboard/` | Counters for the caller's scope |
| `GET POST plans/` · `PATCH DELETE plans/{id}/` | Writes: super admin |
| `GET POST businesses/` · `GET PATCH businesses/{id}/` | `?search= &status=`; writes: staff |
| `POST businesses/{id}/suspend/` · `/activate/` | Staff |
| `GET POST businesses/{id}/domains/` | Nested route from the brief |
| `GET POST domains/` · `GET DELETE domains/{id}/` | `?search= &status= &business=` |
| `POST domains/{id}/verify/` · `/regenerate-token/` · `/check-dns/` · `GET /dns-status/` | |
| `POST domains/{id}/verify-manually/` · `/retry-provisioning/` · `/suspend/` · `/activate/` | Staff |
| `GET POST domains/{id}/mailboxes/` · `GET POST domains/{id}/aliases/` | Nested routes from the brief |
| `GET POST mailboxes/` · `GET PATCH DELETE mailboxes/{id}/` | `?domain= &status= &search= &outbound_suspended=true`; create returns `temporary_password` once |
| `POST mailboxes/{id}/suspend/` · `/activate/` · `/disable/` · `/reset-password/` · `/suspend-outbound/` | |
| `POST mailboxes/{id}/restore-outbound/` | Staff |
| `GET POST aliases/` · `GET PATCH DELETE aliases/{id}/` | |
| `GET security-events/` · `GET security-events/{id}/` · `POST …/resolve/` | `?open= &severity= &event_type=`; resolve: staff |
| `GET audit-logs/` | `?action=domain. &actor= &search=` |
| `GET POST users/` · `PATCH DELETE users/{id}/` · `POST …/reset-password/` · `POST …/reset-2fa/` | Scoped by role |
| `GET monitoring/reputation/` · `GET monitoring/alerts/` · `POST monitoring/alerts/{id}/acknowledge/` | Staff |
| `POST monitoring/run/` | `{"job": "health"\|"blacklists"\|"sync"\|"abuse"\|"dns"}`; super admin |
| `POST monitoring/backup-report/` | `Authorization: Bearer $BACKUP_REPORT_TOKEN`; used by the backup job |

Outside `/api/`: `GET /healthz` (liveness), `GET /readyz` (DB + cache), `GET /metrics` (Prometheus; allow-listed networks only).

---

## 9. Operations runbook

**Onboard a customer.** Businesses → Create business (pick a plan) → Portal users → Invite a business admin for it (share the temporary password by phone or another channel). The customer adds their domain, publishes the TXT record, then follows the setup slip.

**A mailbox was auto-blocked for sending.** It appears under Security events and in your alert e-mail. Ask the customer to change the password (Mailboxes → Reset password) and check their devices; review the event's source IPs. Then Mailboxes → Manage → Allow sending, and resolve the event with a note.

**The mail IP is blacklisted.** Mail server health shows the lists. Find the sender in Security events, block it, fix the cause, then request delisting from each list. Spamhaus ignores queries from public resolvers — set `DNSBL_RESOLVERS` to a local resolver for accurate results.

**Mailcow API alerts ("cannot authenticate").** Check `MAILCOW_API_KEY` matches `mailcow.conf`, and that `API_ALLOW_FROM` contains the app server's current public IP. Verify with `docker compose exec backend python manage.py check_mailcow`.

**Rotate the Mailcow API key.** Generate a new key in `mailcow.conf`, `docker compose up -d` on the mail server, update `.env` on the app server, `docker compose up -d`.

**Admin lost their phone.** Another staff member: Portal users → Manage → Reset two-factor. They enrol again at next sign-in. If the only super admin is locked out: `docker compose exec backend python manage.py shell -c "from apps.accounts.models import User; u=User.objects.get(email='…'); u.disable_totp(); u.save()"`.

**Disaster recovery.** Mail server: deploy/mailcow/README.md §7. App server: fresh server, restore `.env` from your password manager, `docker compose up -d`, then `deploy/scripts/restore-app-db.sh`, then trigger Sync from Mail server health. Targets from the brief: RPO 24 h (6 h with cold standby), RTO 4 h — rehearse both before launch.

**Logs.** `docker compose logs -f backend worker` — every line carries the request ID shown in API error responses.

---

## 10. Testing

```bash
cd backend && pytest            # 129 tests
cd frontend && npm run build    # strict TypeScript type-check + production build
```

The backend suite runs the real Mailcow HTTP client against a stateful fake Mailcow (served through `responses`) and replaces DNS with an in-memory resolver, so it covers request formats, error parsing and full workflows without external services. It includes:

- authentication: CSRF, lockout, 2FA enrolment, OTP replay, recovery codes, password reset without enumeration, setup gating, suspended tenants;
- tenant isolation and RBAC: cross-tenant reads, writes, deletes and creates; ignored client business ids; role escalation attempts;
- domain lifecycle: validation (IDN, reserved names), verification, provisioning with retries and failure alerts, idempotency, DNS evaluation (SPF variants, split DKIM records, DMARC, PTR), regressions;
- mailboxes and aliases: quotas, conflicts, rollback when Mailcow fails, compensation when a later step fails, password never persisted, status mapping;
- background jobs: sync drift correction and import, abuse rules, health, blacklists, backups, alert de-duplication.

CI (`.github/workflows/ci.yml`) runs lint, tests with coverage, a migration-drift check, the frontend build and both Docker image builds.

---

## 11. Known limitations and pre-launch checks

Verify these during the pilot phase (brief §40, phases 5–6), against your exact Mailcow version:

1. **Outbound block mechanism.** Sending blocks set the mailbox attribute `smtp_access=0` (Mailcow 2023+). Confirm it also stops sending from SOGo webmail on your version; the per-mailbox rate limit stays in place as a backstop either way.
2. **Log formats.** Abuse detection parses Rspamd history, rate-limit and Dovecot logs defensively. Generate test traffic (bulk send, wrong passwords) on a pilot mailbox and confirm events appear.
3. **Inbox placement.** Send to Gmail, Outlook, Yahoo, Zoho and iCloud and check inbox vs spam with the domain fully set up. Warm the IP gradually; don't onboard many customers at once.
4. **Restore drills.** Do one full Mailcow restore and one app DB restore on throwaway servers before launch, and monthly after.
5. **Mailbox-user 2FA** is Mailcow/SOGo's own TFA; this portal enforces 2FA for admins only.
6. **Billing** is not integrated; plans are limits only.
7. **The Django admin** has no 2FA and is disabled unless `ADMIN_URL` is set.
