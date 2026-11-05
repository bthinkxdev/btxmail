#!/usr/bin/env bash
# Deploy the portal (app server) from GitHub to the production host over SSH.
#
#   ./deploy.sh                 pull main, rebuild changed images, restart, health-check
#   ./deploy.sh --no-build      pull and restart only (no image rebuild)
#   ./deploy.sh --reset         hard-reset the server checkout to origin/main (after a history rewrite)
#   ./deploy.sh backend web     rebuild/restart only the named services
#
# Overrides (environment):
#   DEPLOY_HOST=ubuntu@16.176.104.237   DEPLOY_KEY=./btxmail.pem   APP_DIR=/opt/btxmail   BRANCH=main
# The server keeps its own .env (never in git) and docker-compose.override.yml
# (template: deploy/server/docker-compose.override.yml, installed on first deploy).
set -Eeuo pipefail
cd "$(dirname "$0")"

HOST=${DEPLOY_HOST:-ubuntu@16.176.104.237}
KEY=${DEPLOY_KEY:-./btxmail.pem}
APP_DIR=${APP_DIR:-/opt/btxmail}
BRANCH=${BRANCH:-main}
BUILD=1 RESET=0 SERVICES=()
for a in "$@"; do
  case $a in
    --no-build) BUILD=0 ;;
    --reset)    RESET=1 ;;
    -h|--help)  sed -n '2,12p' "$0"; exit 0 ;;
    -*)         echo "unknown option: $a" >&2; exit 2 ;;
    *)          SERVICES+=("$a") ;;
  esac
done

[ -f "$KEY" ] || { echo "SSH key not found: $KEY (set DEPLOY_KEY)" >&2; exit 1; }
chmod 600 "$KEY" 2>/dev/null || true
SSH=(ssh -i "$KEY" -o ServerAliveInterval=30 -o ServerAliveCountMax=20 "$HOST")

# The server pulls from GitHub, so what is deployed is what is pushed. Refuse to deploy a surprise.
git fetch -q origin "$BRANCH"
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "Uncommitted changes — commit and push them first; the server deploys from GitHub." >&2; exit 1
fi
if [ -n "$(git log --oneline "origin/$BRANCH..HEAD")" ]; then
  echo "Local commits are not pushed to origin/$BRANCH — push first." >&2; exit 1
fi

echo "==> Deploying origin/$BRANCH ($(git rev-parse --short "origin/$BRANCH")) to $HOST:$APP_DIR"
"${SSH[@]}" bash -s -- "$APP_DIR" "$BRANCH" "$BUILD" "$RESET" "${SERVICES[*]:-}" <<'REMOTE'
set -Eeuo pipefail
APP_DIR=$1 BRANCH=$2 BUILD=$3 RESET=$4 SERVICES=${5:-}
cd "$APP_DIR"

git fetch -q origin "$BRANCH"
if [ "$RESET" = 1 ]; then git reset -q --hard "origin/$BRANCH"; else git merge -q --ff-only "origin/$BRANCH"; fi
echo "server at $(git log --oneline -1)"

[ -f .env ] || { echo ".env is missing on the server — create it from .env.example" >&2; exit 1; }
[ -f docker-compose.override.yml ] || cp deploy/server/docker-compose.override.yml docker-compose.override.yml

if [ "$BUILD" = 1 ]; then
  # 2 GB host: build one image at a time; --pull is skipped to keep it quick.
  sudo docker compose build $SERVICES
fi
sudo docker compose up -d --remove-orphans $SERVICES
sudo docker image prune -f >/dev/null

echo "==> waiting for containers to become healthy"
for i in $(seq 1 30); do
  bad=$(sudo docker compose ps --format '{{.Name}} {{.Status}}' | grep -E 'unhealthy|starting|Restarting|Exited' || true)
  [ -z "$bad" ] && break
  sleep 5
done
sudo docker compose ps --format 'table {{.Name}}\t{{.Status}}'
[ -z "$bad" ] || { echo "Not healthy: $bad" >&2; sudo docker compose logs --tail 30 backend >&2; exit 1; }

host=$(grep -E '^PORTAL_HOSTNAME=' .env | cut -d= -f2-)
code=$(curl -sk -o /dev/null -w '%{http_code}' --resolve "$host:443:127.0.0.1" "https://$host/healthz" || true)
echo "portal /healthz -> $code"
[ "$code" = 200 ]
REMOTE
echo "==> Deploy finished"
