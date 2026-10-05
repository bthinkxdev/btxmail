#!/usr/bin/env bash
# Nightly PostgreSQL backup of the control-plane database → encrypted → offsite.
# Runs on the APP SERVER from the repository directory, e.g. cron:
#   15 1 * * * root cd /opt/bthinkx-mail && deploy/scripts/backup-app-db.sh >> /var/log/bthinkx-db-backup.log 2>&1
set -Eeuo pipefail
cd "$(dirname "$0")/../.."
# Read single keys from .env (it is a docker env-file, not a shell script: values may contain spaces/<>).
env_get() { { grep -E "^$1=" .env || true; } | tail -n 1 | cut -d= -f2-; }
POSTGRES_USER=${POSTGRES_USER:-$(env_get POSTGRES_USER)}
POSTGRES_DB=${POSTGRES_DB:-$(env_get POSTGRES_DB)}
DB_RCLONE_REMOTE=${DB_RCLONE_REMOTE:-$(env_get DB_RCLONE_REMOTE)}
DB_RETENTION_DAYS=${DB_RETENTION_DAYS:-$(env_get DB_RETENTION_DAYS)}
AGE_RECIPIENTS_FILE=${AGE_RECIPIENTS_FILE:-$(env_get AGE_RECIPIENTS_FILE)}

: "${AGE_RECIPIENTS_FILE:=/etc/bthinkx/backup-recipients.txt}"
: "${DB_RCLONE_REMOTE:?Set DB_RCLONE_REMOTE (e.g. b2:bthinkx-backups/app-db) in .env}"
: "${DB_RETENTION_DAYS:=30}"

stamp=$(date -u +%Y%m%dT%H%M%SZ)
out="/var/backups/bthinkx-db"
mkdir -p "$out" && chmod 700 "$out"
file="${out}/control-plane-${stamp}.sql.gz.age"

docker compose exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=plain --no-owner \
  | gzip -9 | age -R "$AGE_RECIPIENTS_FILE" -o "$file"

rclone copy "$file" "$DB_RCLONE_REMOTE" --immutable --retries 5
find "$out" -name 'control-plane-*.sql.gz.age' -mtime +3 -delete
rclone delete "$DB_RCLONE_REMOTE" --min-age "${DB_RETENTION_DAYS}d" --include 'control-plane-*.sql.gz.age'
echo "[$(date -Is)] database backup uploaded: $(basename "$file")"
