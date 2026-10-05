#!/usr/bin/env bash
# First-time Let's Encrypt certificate for the portal (HTTP-01 via the running nginx).
#   deploy/scripts/issue-certificate.sh admin@bthinkx.com
set -Eeuo pipefail
email=${1:?contact e-mail for Let's Encrypt}
cd "$(dirname "$0")/../.."
# Read single keys from .env (it is a docker env-file, not a shell script: values may contain spaces/<>).
env_get() { { grep -E "^$1=" .env || true; } | tail -n 1 | cut -d= -f2-; }
PORTAL_HOSTNAME=${PORTAL_HOSTNAME:-$(env_get PORTAL_HOSTNAME)}
docker compose up -d web
docker compose --profile tls run --rm --entrypoint certbot certbot certonly \
  --webroot -w /var/www/certbot -d "$PORTAL_HOSTNAME" --email "$email" --agree-tos --no-eff-email --non-interactive
docker compose restart web
docker compose --profile tls up -d certbot
echo "Certificate installed for ${PORTAL_HOSTNAME}; renewal runs in the certbot container."
