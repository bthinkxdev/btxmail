#!/bin/sh
# Called by Dovecot (Sieve "execute") once per delivered message.
#   $1 = recipient address, stdin = the message.
# Sends the start of the message (first 128 KB) to the portal, which reads the sender, subject and the first words of
# the body in memory to build the push notification. Nothing is stored or logged. Never fails delivery: every error is
# swallowed and the script always exits 0.

. /etc/dovecot/sieve-bin/portal-hook.env   # PORTAL_HOOK_URL (.../api/push/new-mail-raw/), PORTAL_HOOK_TOKEN

rcpt=$(printf '%s' "$1" | tr -d '\r\n')
[ -n "$rcpt" ] || exit 0

head -c 131072 | curl -fsS -m 3 -o /dev/null \
  -H "Authorization: Bearer ${PORTAL_HOOK_TOKEN}" \
  -H "X-Recipient: ${rcpt}" \
  -H "Content-Type: message/rfc822" \
  --data-binary @- "$PORTAL_HOOK_URL" >/dev/null 2>&1 || true
exit 0
