#!/usr/bin/env bash
# Install / refresh the BThinkX Mail (webmail) PWA on the Mailcow host. Idempotent; run as root (or with sudo)
# from this directory. Re-run after every Mailcow update (update.sh can restore custom-sogo.js).
#
#   sudo ./install.sh [/opt/mailcow-dockerized]
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

# custom-sogo.js is bind-mounted as a single file: rewrite it in place (same inode), never replace it.
tmp=$(mktemp)
sed '/^\/\/ >>> BThinkX PWA/,/^\/\/ <<< BThinkX PWA/d' "$SOGO" > "$tmp"
cat "$HERE/pwa.js" >> "$tmp"
cat "$tmp" > "$SOGO"
rm -f "$tmp"
echo "BThinkX webmail PWA installed. Hard-refresh the inbox (Ctrl+F5) to pick it up."
