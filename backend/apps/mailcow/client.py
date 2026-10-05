"""
Low-level HTTP client for the Mailcow REST API (v1).

Only this module performs HTTP. Higher-level modules (domains, mailboxes, …)
express intent; views and services never call Mailcow directly.

Mailcow conventions handled here:
* Authentication: `X-API-Key` header (read-write key for mutations).
* Mutations return a list of `{"type": "success|danger|error|warning", "msg": …}`.
* `get/<object>/<id>` returns `{}` when the object does not exist and
  `get/<object>/all` returns `{}` (not `[]`) when empty, or a bare dict if
  exactly one item exists on some versions.
"""

from __future__ import annotations

import logging
from typing import Any

import requests
from django.conf import settings
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .exceptions import (
    MailcowAPIError,
    MailcowAuthError,
    MailcowNotConfigured,
    MailcowUnavailable,
)

logger = logging.getLogger(__name__)

_ERROR_TYPES = {"danger", "error"}


def _flatten_msg(msg: Any) -> tuple[str, list[str]]:
    """Mailcow `msg` may be a string, or a list like ["object_exists", "a@b.c"]."""
    if msg is None:
        return "", []
    if isinstance(msg, str):
        return msg, [msg]
    if isinstance(msg, list | tuple):
        parts = [str(p) for p in msg]
        return " ".join(parts), parts[:1]
    return str(msg), [str(msg)]


class MailcowClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        *,
        timeout: int | None = None,
        verify_tls: bool | None = None,
    ):
        self.base_url = (base_url if base_url is not None else settings.MAILCOW_API_URL).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.MAILCOW_API_KEY
        self.timeout = timeout or settings.MAILCOW_TIMEOUT
        self.verify_tls = settings.MAILCOW_VERIFY_TLS if verify_tls is None else verify_tls
        self._session: requests.Session | None = None

    # ------------------------------------------------------------------ #
    @property
    def session(self) -> requests.Session:
        if self._session is None:
            if not self.base_url or not self.api_key:
                raise MailcowNotConfigured("MAILCOW_API_URL and MAILCOW_API_KEY must be configured.")
            session = requests.Session()
            # Retry idempotent reads only; mutations are retried by Celery with backoff.
            retry = Retry(
                total=3,
                connect=3,
                read=2,
                backoff_factor=0.5,
                status_forcelist=(502, 503, 504),
                allowed_methods=frozenset({"GET"}),
                raise_on_status=False,
            )
            adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=8)
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            session.headers.update(
                {
                    "X-API-Key": self.api_key,
                    "Accept": "application/json",
                    "User-Agent": "BThinkX-Control-Plane/1.0",
                }
            )
            self._session = session
        return self._session

    def _url(self, path: str) -> str:
        return f"{self.base_url}/api/v1/{path.lstrip('/')}"

    def _request(self, method: str, path: str, payload: Any = None) -> Any:
        url = self._url(path)
        try:
            response = self.session.request(method, url, json=payload, timeout=self.timeout, verify=self.verify_tls)
        except requests.Timeout as exc:
            raise MailcowUnavailable(f"Timed out calling Mailcow ({method} {path})") from exc
        except requests.RequestException as exc:
            raise MailcowUnavailable(f"Cannot reach Mailcow ({method} {path}): {exc.__class__.__name__}") from exc

        if response.status_code in (401, 403):
            raise MailcowAuthError(
                "Mailcow rejected the API key (check MAILCOW_API_KEY and the API allow-list).",
                status_code=response.status_code,
            )
        if response.status_code >= 500:
            raise MailcowUnavailable(f"Mailcow returned HTTP {response.status_code}", status_code=response.status_code)
        if response.status_code >= 400:
            raise MailcowAPIError(f"Mailcow returned HTTP {response.status_code}", status_code=response.status_code)

        try:
            data = response.json()
        except ValueError as exc:
            raise MailcowUnavailable("Mailcow returned a non-JSON response (is the API enabled?)") from exc

        if isinstance(data, dict) and data.get("type") in _ERROR_TYPES:
            text, codes = _flatten_msg(data.get("msg"))
            if "authentication failed" in text.lower():
                raise MailcowAuthError("Mailcow authentication failed.", payload=data)
            raise MailcowAPIError(text or "Mailcow error", codes=codes, payload=data)
        return data

    # ------------------------------------------------------------------ #
    def get(self, path: str) -> Any:
        return self._request("GET", path)

    def get_list(self, path: str) -> list[dict]:
        data = self.get(path)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            return [data] if data else []
        return []

    def get_object(self, path: str) -> dict | None:
        data = self.get(path)
        if isinstance(data, dict):
            return data or None
        if isinstance(data, list):
            return data[0] if data and isinstance(data[0], dict) else None
        return None

    def mutate(self, path: str, payload: Any) -> list[dict]:
        """POST a mutation and raise MailcowAPIError if any message is an error."""
        data = self._request("POST", path, payload)
        messages = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
        errors = [m for m in messages if isinstance(m, dict) and m.get("type") in _ERROR_TYPES]
        if errors:
            texts, codes = [], []
            for err in errors:
                text, err_codes = _flatten_msg(err.get("msg"))
                texts.append(text)
                codes.extend(err_codes)
            raise MailcowAPIError("; ".join(t for t in texts if t) or "Mailcow error", codes=codes, payload=data)
        return messages

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None


def get_client() -> MailcowClient:
    """Factory used everywhere; patched in tests."""
    return MailcowClient()
