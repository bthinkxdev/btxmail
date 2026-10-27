#!/bin/sh
# Called by Dovecot (Sieve "execute") once per delivered message.
#   $1 = recipient address, stdin = the message.
# Sends ONLY the sender, subject and recipient to the portal; the body is never read or transmitted.
# Never fails delivery: every error is swallowed and the script always exits 0.

. /etc/dovecot/sieve-bin/portal-hook.env   # PORTAL_HOOK_URL, PORTAL_HOOK_TOKEN

rcpt="$1"
[ -n "$rcpt" ] || exit 0

# Header block only (stop at the first blank line), continuation lines unfolded, capped at 16 KB.
headers=$(head -c 16384 | tr -d '\r' | awk '/^$/ {exit} /^[ \t]/ {printf " %s", $0; next} {printf "\n%s", $0}')
from=$(printf '%s\n' "$headers" | grep -i -m1 '^From:' | cut -c6- | sed 's/^ *//')
subject=$(printf '%s\n' "$headers" | grep -i -m1 '^Subject:' | cut -c9- | sed 's/^ *//')

json_escape() {
  printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' | tr -d '\000-\037' | cut -c1-900
}

body=$(printf '{"recipient":"%s","sender":"%s","subject":"%s"}' \
  "$(json_escape "$rcpt")" "$(json_escape "$from")" "$(json_escape "$subject")")

curl -fsS -m 3 -o /dev/null \
  -H "Authorization: Bearer ${PORTAL_HOOK_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "$body" "$PORTAL_HOOK_URL" >/dev/null 2>&1 || true
exit 0
