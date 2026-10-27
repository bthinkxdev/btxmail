# New-mail push notifications (Mailcow side)

The portal turns every delivered message into a notification like Gmail's: the sender as title, the subject as text,
the mailbox address and the business name underneath, the BThinkX logo as icon, grouped into "3 new messages" when
several arrive. For that the mail server tells the portal *that* a message arrived. Only **sender, subject and
recipient** are sent; the body is never read.

```text
Postfix -> Dovecot LDA -> global_sieve_after -> notify-portal.sh -> POST https://portal.../api/push/new-mail/
                                                                     (Bearer token, 3 s timeout, never blocks delivery)
```

## Install (mail server)

1. On the **app server** generate the secrets and put them in `.env`, then `docker compose up -d`:

   ```bash
   docker compose run --rm backend manage generate_vapid_keys      # VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY
   openssl rand -hex 32                                            # NEW_MAIL_WEBHOOK_TOKEN
   ```

2. On the **mail server**, in the Mailcow directory:

   ```bash
   mkdir -p data/conf/dovecot/sieve-bin
   cp notify-portal.sh data/conf/dovecot/sieve-bin/ && chmod 755 data/conf/dovecot/sieve-bin/notify-portal.sh
   cp global_sieve_after data/conf/dovecot/global_sieve_after
   cat > data/conf/dovecot/sieve-bin/portal-hook.env <<'EOF'
   PORTAL_HOOK_URL=https://portal.bthinkx.com/api/push/new-mail/
   PORTAL_HOOK_TOKEN=<NEW_MAIL_WEBHOOK_TOKEN>
   EOF
   chmod 640 data/conf/dovecot/sieve-bin/portal-hook.env
   ```

3. Enable the Sieve `execute` extension for global scripts by appending to `data/conf/dovecot/extra.conf`:

   ```conf
   plugin {
     sieve_plugins = sieve_imapsieve sieve_extprograms
     sieve_global_extensions = +vnd.dovecot.execute
     sieve_execute_bin_dir = /etc/dovecot/sieve-bin
   }
   ```

   (If Mailcow's `dovecot.conf` already lists other `sieve_plugins`, keep them in this list.)

4. Apply: `docker compose restart dovecot-mailcow`, then check `docker compose logs dovecot-mailcow | grep -i sieve` for
   compile errors.

## Verify (do this on a pilot mailbox before launch)

1. In the portal: **My account -> Notifications -> Turn on**, then **Send a test**.
2. Follow a mailbox (your own address is followed automatically) and send it a message from outside.
3. A notification should appear within a few seconds. If not, run from the mail server:

   ```bash
   curl -i -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"recipient":"you@yourdomain.com","sender":"Test <t@example.com>","subject":"Hello"}' \
     https://portal.bthinkx.com/api/push/new-mail/
   ```

   `202` means the portal accepted it (check the worker logs). `401` is a wrong token, `404` means
   `NEW_MAIL_WEBHOOK_TOKEN` is not set on the app server.

Sieve `execute` support differs between Mailcow/Dovecot versions, so confirm it on your exact version.

## Safety properties

- Delivery is never delayed or failed by the hook: 3 s timeout, all errors ignored, exit code always 0.
- Spam (`X-Spam: Yes`) is skipped.
- The portal caps pushes at `PUSH_MAIL_RATE_PER_MINUTE` per mailbox (default 30), so a mail flood cannot flood phones.
- Notifications are encrypted end to end by the Web Push protocol; the portal stores no message content.
