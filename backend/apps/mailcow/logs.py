"""
Readers for Mailcow log endpoints used by abuse detection.

Mailcow's log formats differ slightly between releases, so parsing is
defensive: malformed entries are skipped rather than failing the run.
"""

import re
from datetime import UTC, datetime

from .client import MailcowClient, get_client

_AUTH_FAIL_PATTERNS = [
    re.compile(r"auth failed.*?user=<(?P<user>[^>]+)>.*?rip=(?P<ip>[0-9a-fA-F.:]+)", re.I),
    re.compile(r"\((?P<user>[^,()\s]+@[^,()\s]+),(?P<ip>[0-9a-fA-F.:]+)[,)].*?(password mismatch|unknown user)", re.I),
]


def _ts(value) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(float(value)), tz=UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def rspamd_history(count: int, client: MailcowClient | None = None) -> list[dict]:
    """
    Messages scanned by Rspamd. Entries with an authenticated `user` are
    outbound submissions from that mailbox.
    """
    client = client or get_client()
    out = []
    for row in client.get_list(f"get/logs/rspamd-history/{int(count)}"):
        user = str(row.get("user") or "").strip().lower()
        when = _ts(row.get("unix_time"))
        if not when:
            continue
        out.append(
            {
                "user": "" if user in ("", "unknown") else user,
                "time": when,
                "action": str(row.get("action") or "").lower(),
                "ip": row.get("ip") or None,
                "score": row.get("score"),
            }
        )
    return out


def ratelimited(count: int, client: MailcowClient | None = None) -> list[dict]:
    client = client or get_client()
    out = []
    for row in client.get_list(f"get/logs/ratelimited/{int(count)}"):
        when = _ts(row.get("time"))
        user = str(row.get("user") or row.get("from") or "").strip().lower()
        if when and user:
            out.append({"user": user, "time": when, "ip": row.get("ip") or None, "rl_name": row.get("rl_name", "")})
    return out


def auth_failures(count: int, client: MailcowClient | None = None) -> list[dict]:
    client = client or get_client()
    out = []
    for row in client.get_list(f"get/logs/dovecot/{int(count)}"):
        when = _ts(row.get("time"))
        message = str(row.get("message") or "")
        if not when or not message:
            continue
        for pattern in _AUTH_FAIL_PATTERNS:
            match = pattern.search(message)
            if match:
                out.append({"user": match.group("user").lower(), "ip": match.group("ip"), "time": when})
                break
    return out
