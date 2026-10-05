from .client import MailcowClient, get_client

CRITICAL_CONTAINERS = (
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


def container_status(client: MailcowClient | None = None) -> dict[str, str]:
    """Return {container_name: state} from Mailcow's status endpoint."""
    client = client or get_client()
    data = client.get("get/status/containers")
    result = {}
    if isinstance(data, dict):
        for key, info in data.items():
            if isinstance(info, dict):
                name = str(info.get("container") or key)
                result[name] = str(info.get("state", "unknown"))
    return result


def vmail_usage(client: MailcowClient | None = None) -> dict:
    client = client or get_client()
    data = client.get("get/status/vmail")
    if isinstance(data, list):
        data = data[0] if data else {}
    if not isinstance(data, dict):
        return {}
    pct_raw = str(data.get("used_percent", "")).rstrip("%").strip()
    try:
        pct = float(pct_raw)
    except ValueError:
        pct = None
    return {"used": data.get("used"), "total": data.get("total"), "used_percent": pct}


def queue_size(client: MailcowClient | None = None) -> int:
    client = client or get_client()
    return len(client.get_list("get/mailq/all"))


def version(client: MailcowClient | None = None) -> str:
    client = client or get_client()
    data = client.get("get/status/version")
    if isinstance(data, dict):
        return str(data.get("version", ""))
    return ""
