#!/bin/sh
# nginx always reads /etc/nginx/certs/{fullchain,privkey}.pem.
#  * If certbot has issued a certificate, those are symlinks into /etc/letsencrypt/live/<host>/.
#  * Otherwise (first boot) a short-lived self-signed pair is generated *outside* the certbot
#    tree, so nginx can start and answer the ACME HTTP challenge without confusing certbot.
# A background loop re-links and reloads every 6h so issued/renewed certificates are picked up.
set -eu
: "${PORTAL_HOSTNAME:?PORTAL_HOSTNAME must be set}"
le="/etc/letsencrypt/live/${PORTAL_HOSTNAME}"
out="/etc/nginx/certs"
mkdir -p "$out" /etc/nginx/selfsigned

link_certs() {
  if [ -s "$le/fullchain.pem" ] && [ -s "$le/privkey.pem" ]; then
    ln -sf "$le/fullchain.pem" "$out/fullchain.pem"
    ln -sf "$le/privkey.pem" "$out/privkey.pem"
    return 0
  fi
  if [ ! -s /etc/nginx/selfsigned/fullchain.pem ]; then
    echo "tls-bootstrap: no certificate for ${PORTAL_HOSTNAME} yet; using a temporary self-signed one"
    openssl req -x509 -nodes -newkey rsa:2048 -days 30 \
      -keyout /etc/nginx/selfsigned/privkey.pem -out /etc/nginx/selfsigned/fullchain.pem \
      -subj "/CN=${PORTAL_HOSTNAME}" >/dev/null 2>&1
  fi
  ln -sf /etc/nginx/selfsigned/fullchain.pem "$out/fullchain.pem"
  ln -sf /etc/nginx/selfsigned/privkey.pem "$out/privkey.pem"
  return 1
}

link_certs || true
(
  while :; do
    sleep 21600
    link_certs || true
    nginx -s reload 2>/dev/null || true
  done
) &
