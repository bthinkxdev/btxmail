#!/usr/bin/env bash
# Nightly Mailcow backup → encrypted → offsite, then report the result to the portal.
# Runs on the MAIL SERVER (SERVER 2) as root, e.g. from /etc/cron.d/bthinkx-backup:
#   30 1 * * * root /opt/bthinkx/backup-mailcow.sh >> /var/log/bthinkx-backup.log 2>&1
#
# Requires: mailcow-dockerized, age (https://age-encryption.org), rclone (configured remote).
# Config: /etc/bthinkx/backup.env  (see backup.env.example)
set -Eeuo pipefail

CONFIG=${CONFIG:-/etc/bthinkx/backup.env}
# shellcheck disable=SC1090
source "$CONFIG"

: "${MAILCOW_DIR:=/opt/mailcow-dockerized}"
: "${STAGING_DIR:=/var/backups/mailcow}"
: "${LOCAL_RETENTION_DAYS:=3}"
: "${REMOTE_RETENTION_DAYS:=30}"
: "${AGE_RECIPIENTS_FILE:?AGE_RECIPIENTS_FILE must point to an age public key file}"
: "${RCLONE_REMOTE:?RCLONE_REMOTE must be set, e.g. b2:bthinkx-backups/mailcow}"
: "${PORTAL_URL:?PORTAL_URL must be set}"
: "${BACKUP_REPORT_TOKEN:?BACKUP_REPORT_TOKEN must be set}"

stamp=$(date -u +%Y%m%dT%H%M%SZ)
host=$(hostname -f)
archive="${STAGING_DIR}/mailcow-${host}-${stamp}.tar.age"
started=$(date +%s)

report() {
  local status=$1 message=$2
  curl -fsS --max-time 20 -X POST "${PORTAL_URL%/}/api/monitoring/backup-report/" \
    -H "Authorization: Bearer ${BACKUP_REPORT_TOKEN}" -H "Content-Type: application/json" \
    -d "{\"status\":\"${status}\",\"message\":\"${message//\"/\'}\",\"details\":{\"host\":\"${host}\",\"archive\":\"$(basename "$archive")\",\"seconds\":$(( $(date +%s) - started ))}}" \
    || echo "WARN: could not report backup status to the portal"
}
trap 'report failure "Mailcow backup failed on ${host} at line ${LINENO}"' ERR

mkdir -p "$STAGING_DIR"
chmod 700 "$STAGING_DIR"
work=$(mktemp -d "${STAGING_DIR}/run-XXXX")

echo "[$(date -Is)] mailcow backup → ${work}"
# Official Mailcow backup helper: vmail, crypt, redis, rspamd, postfix, mysql (consistent dump).
MAILCOW_BACKUP_LOCATION="$work" THREADS="${THREADS:-2}" \
  "${MAILCOW_DIR}/helper-scripts/backup_and_restore.sh" backup all

# Include mailcow.conf (contains the API key and DB password — that's why the archive is encrypted).
cp "${MAILCOW_DIR}/mailcow.conf" "$work/"

echo "[$(date -Is)] encrypting → ${archive}"
tar -C "$work" -cf - . | age -R "$AGE_RECIPIENTS_FILE" -o "$archive"
rm -rf "$work"

echo "[$(date -Is)] uploading to ${RCLONE_REMOTE}"
rclone copy "$archive" "$RCLONE_REMOTE" --immutable --retries 5
rclone check "$STAGING_DIR" "$RCLONE_REMOTE" --one-way --include "$(basename "$archive")"

echo "[$(date -Is)] pruning"
find "$STAGING_DIR" -maxdepth 1 -name 'mailcow-*.tar.age' -mtime +"$LOCAL_RETENTION_DAYS" -delete
rclone delete "$RCLONE_REMOTE" --min-age "${REMOTE_RETENTION_DAYS}d" --include 'mailcow-*.tar.age'

size=$(du -h "$archive" | cut -f1)
report success "Mailcow backup ${size} uploaded to ${RCLONE_REMOTE}"
echo "[$(date -Is)] done (${size})"
