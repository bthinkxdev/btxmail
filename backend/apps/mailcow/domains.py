from .client import MailcowClient, get_client
from .exceptions import MailcowAPIError


def get_domain(name: str, client: MailcowClient | None = None) -> dict | None:
    client = client or get_client()
    return client.get_object(f"get/domain/{name}")


def list_domains(client: MailcowClient | None = None) -> list[dict]:
    client = client or get_client()
    return client.get_list("get/domain/all")


def create_domain(
    name: str,
    *,
    description: str,
    max_mailboxes: int,
    default_quota_mb: int,
    max_quota_mb: int,
    total_quota_mb: int,
    max_aliases: int,
    rate_limit_per_hour: int,
    client: MailcowClient | None = None,
) -> bool:
    """
    Create the domain. Idempotent: returns False if it already existed
    (the caller has already proven ownership of the domain in Django).
    """
    client = client or get_client()
    payload = {
        "domain": name,
        "description": description[:255],
        "aliases": str(max_aliases),
        "mailboxes": str(max_mailboxes),
        "defquota": str(default_quota_mb),
        "maxquota": str(max_quota_mb),
        "quota": str(total_quota_mb),
        "active": "1",
        "rl_value": str(rate_limit_per_hour),
        "rl_frame": "h",
        "backupmx": "0",
        "relay_all_recipients": "0",
        "restart_sogo": "10",
    }
    try:
        client.mutate("add/domain", payload)
    except MailcowAPIError as exc:
        if exc.has_code("domain_exists"):
            return False
        raise
    return True


def update_domain_limits(
    name: str,
    *,
    max_mailboxes: int,
    default_quota_mb: int,
    max_quota_mb: int,
    total_quota_mb: int,
    max_aliases: int,
    client: MailcowClient | None = None,
) -> None:
    client = client or get_client()
    client.mutate(
        "edit/domain",
        {
            "items": [name],
            "attr": {
                "mailboxes": str(max_mailboxes),
                "defquota": str(default_quota_mb),
                "maxquota": str(max_quota_mb),
                "quota": str(total_quota_mb),
                "aliases": str(max_aliases),
            },
        },
    )


def set_domain_active(name: str, active: bool, client: MailcowClient | None = None) -> None:
    client = client or get_client()
    client.mutate("edit/domain", {"items": [name], "attr": {"active": "1" if active else "0"}})


def delete_domain(name: str, client: MailcowClient | None = None) -> None:
    """Mailcow refuses to delete a domain that still has mailboxes."""
    client = client or get_client()
    if get_domain(name, client) is None:
        return
    client.mutate("delete/domain", [name])
