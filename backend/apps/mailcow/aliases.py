from .client import MailcowClient, get_client
from .exceptions import MailcowAPIError


def list_aliases(client: MailcowClient | None = None) -> list[dict]:
    client = client or get_client()
    return client.get_list("get/alias/all")


def find_alias(address: str, client: MailcowClient | None = None) -> dict | None:
    address = address.lower()
    for alias in list_aliases(client):
        if str(alias.get("address", "")).lower() == address:
            return alias
    return None


def create_alias(address: str, destinations: list[str], *, active=True, client: MailcowClient | None = None) -> str:
    """Create an alias and return its Mailcow id."""
    client = client or get_client()
    client.mutate(
        "add/alias",
        {"address": address, "goto": ",".join(destinations), "active": "1" if active else "0"},
    )
    found = find_alias(address, client)
    if not found or found.get("id") in (None, ""):
        raise MailcowAPIError(f"Alias {address} was not found after creation.")
    return str(found["id"])


def update_alias(alias_id: str, destinations: list[str], *, active=True, client: MailcowClient | None = None):
    client = client or get_client()
    client.mutate(
        "edit/alias",
        {"items": [str(alias_id)], "attr": {"goto": ",".join(destinations), "active": "1" if active else "0"}},
    )


def delete_alias(alias_id: str, client: MailcowClient | None = None) -> None:
    client = client or get_client()
    if not alias_id:
        return
    client.mutate("delete/alias", [str(alias_id)])


def alias_exists_error(exc: MailcowAPIError) -> bool:
    return exc.has_code("is_alias_or_mailbox", "alias_domain_invalid", "object_exists", "is_alias")
