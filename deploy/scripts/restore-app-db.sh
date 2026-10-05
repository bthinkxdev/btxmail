#!/usr/bin/env bash
# Restore the control-plane database from an encrypted dump (use for DR and the weekly restore test).
#   deploy/scripts/restore-app-db.sh /path/control-plane-XXXX.sql.gz.age /path/to/age-private-key.txt
set -Eeuo pipefail
dump=${1:?encrypted dump path}
key=${2:?age private key file}
cd "$(dirname "$0")/../.."
# Read single keys from .env (it is a docker env-file, not a shell script: values may contain spaces/<>).
env_get() { { grep -E "^$1=" .env || true; } | tail -n 1 | cut -d= -f2-; }
POSTGRES_USER=${POSTGRES_USER:-$(env_get POSTGRES_USER)}
POSTGRES_DB=${POSTGRES_DB:-$(env_get POSTGRES_DB)}

read -r -p "This REPLACES database ${POSTGRES_DB}. Type the database name to continue: " answer
[ "$answer" = "$POSTGRES_DB" ] || { echo "aborted"; exit 1; }

docker compose stop backend worker beat
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 \
  -c "DROP DATABASE IF EXISTS \"${POSTGRES_DB}\";" -c "CREATE DATABASE \"${POSTGRES_DB}\" OWNER \"${POSTGRES_USER}\";"
age -d -i "$key" "$dump" | gunzip | docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -q
docker compose up -d backend worker beat
echo "Restore complete. Run a Mailcow sync from Mail server health to reconcile."
