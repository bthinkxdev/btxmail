#!/usr/bin/env bash
# Install / refresh the BThinkX Mail (webmail) PWA and its new-mail push bridge on the Mailcow host. Idempotent; run
# as root (or with sudo) from this directory. Re-run after every Mailcow update (update.sh can restore custom-sogo.js).
#
#   sudo ./install.sh [/opt/mailcow-dockerized]
#
# Push bridge settings come from BTX_PORTAL_URL / BTX_HOOK_TOKEN, or from the portal's .env (APP_ENV, default
# /opt/btxmail/.env) when the portal runs on this same host.
set -Eeuo pipefail
MC=${1:-/opt/mailcow-dockerized}
HERE=$(cd "$(dirname "$0")" && pwd)
WEB=$MC/data/web
SOGO=$MC/data/conf/sogo/custom-sogo.js
[ -d "$WEB" ] && [ -f "$SOGO" ] || { echo "Mailcow not found at $MC" >&2; exit 1; }

install -m 0644 "$HERE/manifest.json" "$WEB/bthinkx-manifest.json"
install -m 0644 "$HERE/sw.js"         "$WEB/bthinkx-sw.js"
install -m 0644 "$HERE/offline.html"  "$WEB/bthinkx-offline.html"
install -d -m 0755 "$WEB/img/bthinkx"
install -m 0644 "$HERE"/icons/* "$WEB/img/bthinkx/"

# New-mail push bridge (PHP, runs inside Mailcow's own web container and trusts only the mail-server login).
install -m 0644 "$HERE/bthinkx-push.php" "$WEB/bthinkx-push.php"
APP_ENV=${APP_ENV:-/opt/btxmail/.env}
getenv() { if [ -f "$APP_ENV" ]; then grep -E "^$1=" "$APP_ENV" | tail -n 1 | cut -d= -f2- || true; fi; }
URL=${BTX_PORTAL_URL:-$(getenv PORTAL_URL)}
TOKEN=${BTX_HOOK_TOKEN:-$(getenv NEW_MAIL_WEBHOOK_TOKEN)}
if [ -n "$URL" ] && [ -n "$TOKEN" ]; then
  {
    echo '<?php'
    echo '// Written by install.sh. Executing this file outputs nothing; never publish its contents.'
    echo "return [\"url\" => \"$URL\", \"token\" => \"$TOKEN\"];"
  } > "$WEB/bthinkx-push-config.php"
  chmod 0644 "$WEB/bthinkx-push-config.php"
  echo "Push bridge configured for $URL"
else
  echo "NOTE: no portal URL/token found; set BTX_PORTAL_URL and BTX_HOOK_TOKEN and re-run to enable inbox push." >&2
fi

# custom-sogo.js is bind-mounted as a single file: rewrite it in place (same inode), never replace it.
tmp=$(mktemp)
sed '/^\/\/ >>> BThinkX PWA/,/^\/\/ <<< BThinkX PWA/d' "$SOGO" > "$tmp"
cat "$HERE/pwa.js" >> "$tmp"
cat "$tmp" > "$SOGO"
rm -f "$tmp"
echo "BThinkX webmail PWA installed. Hard-refresh the inbox (Ctrl+F5) to pick it up."
