# Mail server (SERVER 2) — Mailcow setup

This server runs only Mailcow. The BThinkX control plane talks to it over the Mailcow REST API; customers and staff never use the Mailcow admin UI.

## 1. Server

| Item | Recommendation |
| --- | --- |
| OS | Ubuntu 24.04 LTS (Mailcow supports 22.04+) |
| CPU / RAM | 4+ vCPU, 16 GB RAM (Mailcow's documented minimum is 6 GB + 1 GB swap — not enough for production) |
| Disk | 200–500 GB NVMe, sized from plan quotas you sell |
| Network | 1 dedicated IPv4 with a clean reputation, port 25 open outbound (ask the provider), rDNS editable |

Before installing, check the IP on <https://mxtoolbox.com/blacklists.aspx>. Do not start with a listed IP.

## 2. DNS for the platform itself

| Record | Value |
| --- | --- |
| `A mail.bthinkx.com` | the mail server IPv4 |
| `PTR` (set at the VPS provider) | `mail.bthinkx.com` |
| `MX bthinkx.com` | `mail.bthinkx.com` (if BThinkX's own mail lives here) |
| `TXT bthinkx.com` | `v=spf1 mx -all` |

The PTR must match `MAIL_HOSTNAME` exactly; the portal checks this (forward-confirmed reverse DNS) on every domain.

## 3. Install Mailcow

```bash
apt update && apt -y upgrade
apt -y install git curl age rclone ufw
curl -fsSL https://get.docker.com | sh
cd /opt && git clone https://github.com/mailcow/mailcow-dockerized && cd mailcow-dockerized
./generate_config.sh          # hostname: mail.bthinkx.com, timezone: Asia/Kolkata
```

Edit `mailcow.conf`:

```ini
MAILCOW_HOSTNAME=mail.bthinkx.com
# Read-write API for the control plane — generate with: openssl rand -hex 32
API_KEY=<random 64 hex chars>
# Only the app server may call the API (comma-separated IPs/CIDRs)
API_ALLOW_FROM=<APP_SERVER_PUBLIC_IP>
SKIP_CLAMD=n
```

Then:

```bash
docker compose pull && docker compose up -d
```

Put the same `API_KEY` into the app server's `.env` as `MAILCOW_API_KEY`, and confirm from the app server:

```bash
docker compose exec backend python manage.py check_mailcow
```

## 4. Firewall

```bash
ufw default deny incoming
ufw allow 22/tcp                       # restrict to your admin IPs if possible
ufw allow 25,465,587,143,993,110,995,4190/tcp
ufw allow 80,443/tcp                   # webmail, ACME, API (API is IP-restricted by Mailcow)
ufw enable
```

Mailcow's netfilter container bans IPs that fail authentication repeatedly; the portal additionally records these as security events.

## 5. Hardening checklist

- Change the Mailcow admin password and enable TFA for it; keep that account for break-glass use only.
- Keep `API_ALLOW_FROM` limited to the app server.
- Enable unattended security updates: `apt -y install unattended-upgrades`.
- Update Mailcow monthly: `./update.sh` (take a backup first).
- Set the global outbound rate limit in Mailcow as a ceiling; the portal sets per-mailbox limits from plans.

## 6. Backups

1. Create an age key pair **on your laptop**, not the server: `age-keygen -o bthinkx-backup.key`. Store the private key in the company password manager. Copy only the public key line to `/etc/bthinkx/backup-recipients.txt` on the server.
2. Configure an rclone remote for offsite object storage (Backblaze B2, Wasabi, S3): `rclone config`.
3. Install the job:

```bash
mkdir -p /opt/bthinkx /etc/bthinkx
cp backup-mailcow.sh /opt/bthinkx/ && chmod 700 /opt/bthinkx/backup-mailcow.sh
cp backup.env.example /etc/bthinkx/backup.env && chmod 600 /etc/bthinkx/backup.env   # then edit
echo '30 1 * * * root /opt/bthinkx/backup-mailcow.sh >> /var/log/bthinkx-backup.log 2>&1' > /etc/cron.d/bthinkx-backup
/opt/bthinkx/backup-mailcow.sh    # run once now and confirm "Last backup" turns OK in the portal
```

Each run reports to the portal; if no successful report arrives within `BACKUP_MAX_AGE_HOURS`, BThinkX admins are alerted.

## 7. Restore / disaster recovery

On a fresh server with Mailcow installed (same version) and the same hostname:

```bash
rclone copy b2:bthinkx-backups/mailcow/mailcow-<host>-<stamp>.tar.age /root/
mkdir /root/restore && age -d -i bthinkx-backup.key /root/mailcow-*.tar.age | tar -C /root/restore -xf -
cp /root/restore/mailcow.conf /opt/mailcow-dockerized/mailcow.conf
cd /opt/mailcow-dockerized && MAILCOW_BACKUP_LOCATION=/root/restore ./helper-scripts/backup_and_restore.sh restore
```

Point `A mail.bthinkx.com` and the PTR at the new IP, then trigger **Sync mailboxes** in the portal's *Mail server health* page. Practise this monthly on a throwaway VPS — an untested backup is not a backup.

For a warm standby, Mailcow's `create_cold_standby.sh` (in the mailcow-dockerized directory) keeps a second server in sync with rsync; run it every few hours to bring the RPO from 24 h down to about 6 h.
