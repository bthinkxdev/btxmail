from .client import MailcowClient, get_client
from .exceptions import MailcowAPIError


def get_dkim(domain: str, client: MailcowClient | None = None) -> dict | None:
    """Returns {"dkim_selector", "dkim_txt", "pubkey", "length"} or None."""
    client = client or get_client()
    data = client.get_object(f"get/dkim/{domain}")
    if not data or not data.get("dkim_txt"):
        return None
    return data


def ensure_dkim(domain: str, *, selector: str, key_size: int, client: MailcowClient | None = None) -> dict:
    """Generate a DKIM key if missing and return the public record."""
    client = client or get_client()
    existing = get_dkim(domain, client)
    if existing:
        return existing
    client.mutate(
        "add/dkim",
        {"domains": domain, "dkim_selector": selector, "key_size": str(key_size)},
    )
    created = get_dkim(domain, client)
    if not created:
        raise MailcowAPIError(f"DKIM key for {domain} was not returned after creation.")
    return created


def delete_dkim(domain: str, client: MailcowClient | None = None) -> None:
    client = client or get_client()
    if get_dkim(domain, client):
        client.mutate("delete/dkim", [domain])
