"""
A stateful in-memory imitation of the Mailcow API, served through `responses`
so the real MailcowClient (headers, error parsing, retries) is exercised.
"""

from __future__ import annotations

import json
import re
import time
from urllib.parse import urlparse

import responses

BASE = "https://mailcow.test"
API_KEY = "test-api-key"


def ok(*msg):
    return [{"type": "success", "log": [], "msg": list(msg)}]


def danger(*msg):
    return [{"type": "danger", "log": [], "msg": list(msg)}]


class FakeMailcow:
    def __init__(self, rsps: responses.RequestsMock):
        self.domains: dict[str, dict] = {}
        self.mailboxes: dict[str, dict] = {}
        self.aliases: dict[int, dict] = {}
        self.dkim: dict[str, dict] = {}
        self.rate_limits: dict[str, dict] = {}
        self.logs: dict[str, list] = {"rspamd-history": [], "ratelimited": [], "dovecot": []}
        self.containers = {
            name: {"type": "info", "container": name, "state": "running"}
            for name in (
                "postfix-mailcow",
                "dovecot-mailcow",
                "rspamd-mailcow",
                "mysql-mailcow",
                "redis-mailcow",
                "nginx-mailcow",
                "sogo-mailcow",
                "php-fpm-mailcow",
                "unbound-mailcow",
            )
        }
        self.vmail = {"type": "info", "disk": "/dev/sda", "used": "10G", "total": "100G", "used_percent": "10%"}
        self.queue: list[dict] = []
        self.failures: list[tuple[str, str, object]] = []  # (method, path-prefix, status|"danger")
        self.calls: list[tuple[str, str, object]] = []
        self._next_alias_id = 1
        pattern = re.compile(re.escape(BASE) + r"/api/v1/.*")
        rsps.add_callback(responses.GET, pattern, callback=self._dispatch)
        rsps.add_callback(responses.POST, pattern, callback=self._dispatch)

    # ------------------------------------------------------------------ #
    def fail(self, method: str, path_prefix: str, kind: object = 500, times: int = 1):
        for _ in range(times):
            self.failures.append((method, path_prefix, kind))

    def calls_to(self, prefix: str) -> list:
        return [c for c in self.calls if c[1].startswith(prefix)]

    def _dispatch(self, request):
        if request.headers.get("X-API-Key") != API_KEY:
            return 401, {}, json.dumps({"type": "error", "msg": "authentication failed"})
        path = urlparse(request.url).path.split("/api/v1/", 1)[1]
        body = json.loads(request.body) if request.body else None
        self.calls.append((request.method, path, body))
        for i, (method, prefix, kind) in enumerate(self.failures):
            if method == request.method and path.startswith(prefix):
                self.failures.pop(i)
                if kind == "danger":
                    return 200, {}, json.dumps(danger("injected_failure"))
                return int(kind), {}, "upstream error"
        handler = self._get if request.method == "GET" else self._post
        result = handler(path, body)
        return 200, {"Content-Type": "application/json"}, json.dumps(result)

    # ------------------------------------------------------------------ #
    def _get(self, path: str, body):
        parts = path.split("/")
        obj, ident = parts[1], "/".join(parts[2:])
        if obj == "domain":
            if ident == "all":
                return list(self.domains.values()) or {}
            return self.domains.get(ident, {})
        if obj == "mailbox":
            if ident == "all":
                return list(self.mailboxes.values()) or {}
            return self.mailboxes.get(ident, {})
        if obj == "alias":
            return list(self.aliases.values()) or {}
        if obj == "dkim":
            return self.dkim.get(ident, {})
        if obj == "status":
            if ident == "containers":
                return self.containers
            if ident == "vmail":
                return self.vmail
            if ident == "version":
                return {"version": "2026-09"}
        if obj == "mailq":
            return self.queue
        if obj == "logs":
            kind = parts[2]
            return self.logs.get(kind, [])
        return {}

    def _post(self, path: str, body):
        verb, obj = path.split("/")[:2]
        if verb == "add" and obj == "domain":
            name = body["domain"]
            if name in self.domains:
                return danger("domain_exists", name)
            self.domains[name] = {"domain_name": name, "active": "1", **body}
            return ok("domain_added", name)
        if verb == "edit" and obj == "domain":
            for name in body["items"]:
                if name not in self.domains:
                    return danger("domain_not_found", name)
                self.domains[name].update(body["attr"])
            return ok("domain_modified")
        if verb == "delete" and obj == "domain":
            for name in body:
                if any(m["domain"] == name for m in self.mailboxes.values()):
                    return danger("domain_not_empty", name)
                self.domains.pop(name, None)
            return ok("domain_removed")
        if verb == "add" and obj == "dkim":
            domain = body["domains"]
            pub = "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA" + domain.replace(".", "")
            self.dkim[domain] = {
                "pubkey": pub,
                "length": body["key_size"],
                "dkim_selector": body["dkim_selector"],
                "dkim_txt": f"v=DKIM1;k=rsa;t=s;s=email;p={pub}",
                "privkey": "",
            }
            return ok("dkim_added", domain)
        if verb == "delete" and obj == "dkim":
            for d in body:
                self.dkim.pop(d, None)
            return ok("dkim_removed")
        if verb == "add" and obj == "mailbox":
            address = f"{body['local_part']}@{body['domain']}"
            if body["domain"] not in self.domains:
                return danger("domain_not_found", body["domain"])
            if address in self.mailboxes or any(a["address"] == address for a in self.aliases.values()):
                return danger("object_exists", address)
            if body["password"] != body["password2"] or len(body["password"]) < 8:
                return danger("password_complexity")
            self.mailboxes[address] = {
                "username": address,
                "domain": body["domain"],
                "local_part": body["local_part"],
                "name": body["name"],
                "active": body["active"],
                "active_int": int(body["active"]),
                "quota": int(body["quota"]) * 1024 * 1024,
                "quota_used": 0,
                "messages": 0,
                "attributes": {"smtp_access": "1", "force_pw_update": body["force_pw_update"]},
                "last_imap_login": "0",
                "_password": body["password"],
            }
            return ok("mailbox_added", address)
        if verb == "edit" and obj == "mailbox":
            for address in body["items"]:
                mb = self.mailboxes.get(address)
                if mb is None:
                    return danger("access_denied")
                attr = body["attr"]
                if "active" in attr:
                    mb["active"] = attr["active"]
                    mb["active_int"] = int(attr["active"])
                if "quota" in attr:
                    mb["quota"] = int(attr["quota"]) * 1024 * 1024
                if "name" in attr:
                    mb["name"] = attr["name"]
                if "password" in attr:
                    mb["_password"] = attr["password"]
                for key in ("smtp_access", "force_pw_update"):
                    if key in attr:
                        mb["attributes"][key] = attr[key]
            return ok("mailbox_modified")
        if verb == "edit" and obj == "rl-mbox":
            for address in body["items"]:
                self.rate_limits[address] = body["attr"]
            return ok("rl_saved")
        if verb == "delete" and obj == "mailbox":
            for address in body:
                self.mailboxes.pop(address, None)
            return ok("mailbox_removed")
        if verb == "add" and obj == "alias":
            address = body["address"]
            if address in self.mailboxes or any(a["address"] == address for a in self.aliases.values()):
                return danger("is_alias_or_mailbox", address)
            alias_id = self._next_alias_id
            self._next_alias_id += 1
            self.aliases[alias_id] = {
                "id": alias_id,
                "address": address,
                "goto": body["goto"],
                "active": body["active"],
            }
            return ok("alias_added", address)
        if verb == "edit" and obj == "alias":
            for alias_id in body["items"]:
                alias = self.aliases.get(int(alias_id))
                if alias is None:
                    return danger("access_denied")
                alias.update(body["attr"])
            return ok("alias_modified")
        if verb == "delete" and obj == "alias":
            for alias_id in body:
                self.aliases.pop(int(alias_id), None)
            return ok("alias_removed")
        return danger("unknown_endpoint", path)

    # ------------------------------------------------------------------ #
    def add_outbound(self, user: str, count: int, *, action: str = "no action", age_seconds: int = 60):
        now = int(time.time()) - age_seconds
        for _ in range(count):
            self.logs["rspamd-history"].append(
                {"unix_time": now, "user": user, "action": action, "ip": "198.51.100.7", "score": 1.0}
            )
