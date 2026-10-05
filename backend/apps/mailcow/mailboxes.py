from datetime import UTC, datetime

from .client import MailcowClient, get_client
from .exceptions import MailcowAPIError

# Mailcow "active" values: 1 = active, 0 = inactive, 2 = login disallowed (still receives mail)
ACTIVE = "1"
INACTIVE = "0"
LOGIN_DISALLOWED = "2"


def get_mailbox(address: str, client: MailcowClient | None = None) -> dict | None:
    client = client or get_client()
    return client.get_object(f"get/mailbox/{address}")


def list_mailboxes(client: MailcowClient | None = None) -> list[dict]:
    client = client or get_client()
    return client.get_list("get/mailbox/all")


def create_mailbox(
    *,
    local_part: str,
    domain: str,
    name: str,
    quota_mb: int,
    password: str,
    force_password_change: bool = True,
    client: MailcowClient | None = None,
) -> None:
    client = client or get_client()
    client.mutate(
        "add/mailbox",
        {
            "local_part": local_part,
            "domain": domain,
            "name": name,
            "quota": str(quota_mb),
            "password": password,
            "password2": password,
            "active": ACTIVE,
            "force_pw_update": "1" if force_password_change else "0",
            "tls_enforce_in": "1",
            "tls_enforce_out": "0",
        },
    )


def edit_mailbox(address: str, attrs: dict, client: MailcowClient | None = None) -> None:
    client = client or get_client()
    client.mutate("edit/mailbox", {"items": [address], "attr": attrs})


def set_password(address: str, password: str, *, force_change: bool = True, client: MailcowClient | None = None):
    edit_mailbox(
        address,
        {"password": password, "password2": password, "force_pw_update": "1" if force_change else "0"},
        client,
    )


def set_active_state(address: str, state: str, client: MailcowClient | None = None) -> None:
    if state not in (ACTIVE, INACTIVE, LOGIN_DISALLOWED):
        raise ValueError(f"Invalid mailbox state {state}")
    edit_mailbox(address, {"active": state}, client)


def set_smtp_access(address: str, allowed: bool, client: MailcowClient | None = None) -> None:
    """Allow/deny authenticated SMTP submission. Incoming mail is unaffected."""
    edit_mailbox(address, {"smtp_access": "1" if allowed else "0"}, client)


def set_rate_limit(address: str, per_hour: int, client: MailcowClient | None = None) -> None:
    client = client or get_client()
    client.mutate("edit/rl-mbox", {"items": [address], "attr": {"rl_value": str(per_hour), "rl_frame": "h"}})


def delete_mailbox(address: str, client: MailcowClient | None = None) -> None:
    client = client or get_client()
    if get_mailbox(address, client) is None:
        return
    client.mutate("delete/mailbox", [address])


def mailbox_exists_error(exc: MailcowAPIError) -> bool:
    return exc.has_code("object_exists", "mailbox_exists", "is_alias_or_mailbox", "is_alias")


# --------------------------------------------------------------------------- #
# Parsing helpers for sync
# --------------------------------------------------------------------------- #
def _to_int(value, default=0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def parse_mailbox(raw: dict) -> dict:
    """Normalize a Mailcow mailbox record into the fields the platform uses."""
    attrs = raw.get("attributes") or {}
    last_login = 0
    for key in ("last_imap_login", "last_pop3_login", "last_smtp_login"):
        last_login = max(last_login, _to_int(raw.get(key)))
    active = str(raw.get("active_int", raw.get("active", "1")))
    return {
        "username": str(raw.get("username", "")).lower(),
        "active": active,
        "quota_bytes": _to_int(raw.get("quota")),
        "used_bytes": _to_int(raw.get("quota_used")),
        "messages": _to_int(raw.get("messages")),
        "name": raw.get("name") or "",
        "smtp_access": str(attrs.get("smtp_access", "1")) == "1",
        "last_login_at": datetime.fromtimestamp(last_login, tz=UTC) if last_login > 0 else None,
    }
