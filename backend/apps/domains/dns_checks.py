"""
DNS verification and health checks for customer domains.

All lookups use an explicit resolver list (DNS_RESOLVERS) with a hard
timeout so a broken customer zone can never hang a worker.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import dns.exception
import dns.name
import dns.resolver
import dns.reversename
from django.conf import settings

logger = logging.getLogger(__name__)

PASS, FAIL, WARN, UNKNOWN = "PASS", "FAIL", "WARN", "UNKNOWN"

_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")


class DNSLookupError(Exception):
    """Transient resolver failure (timeout, SERVFAIL) — result is UNKNOWN, not FAIL."""


@dataclass
class CheckResult:
    status: str
    message: str
    found: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"status": self.status, "message": self.message, "found": self.found}


# --------------------------------------------------------------------------- #
# Name handling
# --------------------------------------------------------------------------- #
def normalize_domain(value: str) -> str:
    """
    Lower-case, strip, IDNA-encode and validate a domain name.
    Raises ValueError with a user-facing message if invalid.
    """
    raw = (value or "").strip().lower().rstrip(".")
    if raw.startswith(("http://", "https://")) or "/" in raw or "@" in raw or " " in raw:
        raise ValueError("Enter a bare domain name such as example.com.")
    try:
        ascii_name = raw.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("Domain name contains invalid characters.") from exc
    if len(ascii_name) > 253 or "." not in ascii_name:
        raise ValueError("Enter a valid domain name such as example.com.")
    labels = ascii_name.split(".")
    if not all(_LABEL.match(label) for label in labels):
        raise ValueError("Enter a valid domain name such as example.com.")
    if labels[-1].isdigit():
        raise ValueError("IP addresses are not allowed.")
    if ascii_name == settings.MAIL_HOSTNAME or ascii_name.endswith("." + settings.MAIL_HOSTNAME):
        raise ValueError("This domain is reserved by the platform.")
    return ascii_name


# --------------------------------------------------------------------------- #
# Resolver primitives
# --------------------------------------------------------------------------- #
def _resolver(nameservers: list[str] | None = None) -> dns.resolver.Resolver:
    servers = nameservers if nameservers is not None else settings.DNS_RESOLVERS
    resolver = dns.resolver.Resolver(configure=not servers)
    if servers:
        resolver.nameservers = servers
    resolver.timeout = settings.DNS_TIMEOUT
    resolver.lifetime = settings.DNS_TIMEOUT * 2
    resolver.cache = None
    return resolver


def _query(name: str, rdtype: str, nameservers: list[str] | None = None):
    try:
        return list(_resolver(nameservers).resolve(name, rdtype, raise_on_no_answer=False) or [])
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return []
    except dns.resolver.NoNameservers as exc:
        raise DNSLookupError(f"No nameserver answered for {name} {rdtype}") from exc
    except dns.exception.Timeout as exc:
        raise DNSLookupError(f"DNS timeout for {name} {rdtype}") from exc
    except dns.exception.DNSException as exc:
        raise DNSLookupError(f"DNS error for {name} {rdtype}: {exc.__class__.__name__}") from exc


def txt_records(name: str) -> list[str]:
    records = []
    for rdata in _query(name, "TXT"):
        records.append(b"".join(rdata.strings).decode("utf-8", errors="replace"))
    return records


def mx_records(name: str) -> list[tuple[int, str]]:
    return sorted((int(r.preference), str(r.exchange).rstrip(".").lower()) for r in _query(name, "MX"))


def a_records(name: str) -> list[str]:
    return [r.address for r in _query(name, "A")]


# --------------------------------------------------------------------------- #
# Checks
# --------------------------------------------------------------------------- #
def check_verification(domain_name: str, token: str) -> CheckResult:
    name = f"{settings.DOMAIN_VERIFICATION_PREFIX}.{domain_name}"
    try:
        records = txt_records(name)
    except DNSLookupError as exc:
        return CheckResult(UNKNOWN, str(exc))
    if any(r.strip() == token for r in records):
        return CheckResult(PASS, "Verification record found.", records)
    if records:
        return CheckResult(FAIL, "TXT record found but the value does not match.", records)
    return CheckResult(FAIL, f"No TXT record at {name}.")


def check_mx(domain_name: str) -> CheckResult:
    try:
        records = mx_records(domain_name)
    except DNSLookupError as exc:
        return CheckResult(UNKNOWN, str(exc))
    found = [f"{p} {h}" for p, h in records]
    if not records:
        return CheckResult(FAIL, "No MX records.", found)
    hosts = {h for _, h in records}
    if hosts == {settings.MAIL_HOSTNAME}:
        return CheckResult(PASS, "MX points to the platform.", found)
    if settings.MAIL_HOSTNAME in hosts:
        return CheckResult(WARN, "MX includes the platform but also other servers.", found)
    return CheckResult(FAIL, f"MX must point to {settings.MAIL_HOSTNAME}.", found)


def _spf_authorizes_platform(record: str) -> bool:
    terms = record.lower().split()[1:]
    for term in terms:
        mech = term.lstrip("+")
        if mech in ("mx", f"mx:{settings.MAIL_HOSTNAME}", f"a:{settings.MAIL_HOSTNAME}"):
            return True
        if settings.MAIL_IPV4 and mech in (f"ip4:{settings.MAIL_IPV4}", f"ip4:{settings.MAIL_IPV4}/32"):
            return True
        if mech.startswith("include:") and mech.split(":", 1)[1] == settings.MAIL_HOSTNAME:
            return True
    return False


def check_spf(domain_name: str) -> CheckResult:
    try:
        records = [r for r in txt_records(domain_name) if r.lower().startswith("v=spf1")]
    except DNSLookupError as exc:
        return CheckResult(UNKNOWN, str(exc))
    if not records:
        return CheckResult(FAIL, "No SPF record.")
    if len(records) > 1:
        return CheckResult(FAIL, "Multiple SPF records found; merge them into one.", records)
    record = records[0]
    if not _spf_authorizes_platform(record):
        return CheckResult(FAIL, "SPF record does not authorize the platform mail server.", records)
    if record.rstrip().lower().endswith(("+all", " all")):
        return CheckResult(WARN, "SPF ends with +all, which allows anyone to send as this domain.", records)
    if "~all" in record.lower() or "?all" in record.lower():
        return CheckResult(WARN, "SPF uses soft-fail; -all is recommended.", records)
    return CheckResult(PASS, "SPF authorizes the platform.", records)


def _extract_p(value: str) -> str:
    for part in value.replace(" ", "").split(";"):
        if part.lower().startswith("p="):
            return part[2:]
    return ""


def check_dkim(domain_name: str, selector: str, expected_record: str) -> CheckResult:
    if not expected_record:
        return CheckResult(UNKNOWN, "DKIM key has not been generated yet.")
    name = f"{selector}._domainkey.{domain_name}"
    try:
        records = txt_records(name)
    except DNSLookupError as exc:
        return CheckResult(UNKNOWN, str(exc))
    if not records:
        return CheckResult(FAIL, f"No DKIM record at {name}.")
    expected_p = _extract_p(expected_record)
    if any(_extract_p(r) == expected_p and expected_p for r in records):
        return CheckResult(PASS, "DKIM public key matches.", records)
    return CheckResult(FAIL, "DKIM record does not match the platform key.", records)


def check_dmarc(domain_name: str) -> CheckResult:
    try:
        records = [r for r in txt_records(f"_dmarc.{domain_name}") if r.lower().startswith("v=dmarc1")]
    except DNSLookupError as exc:
        return CheckResult(UNKNOWN, str(exc))
    if not records:
        return CheckResult(FAIL, "No DMARC record.")
    if len(records) > 1:
        return CheckResult(FAIL, "Multiple DMARC records found.", records)
    policy = ""
    for part in records[0].replace(" ", "").split(";"):
        if part.lower().startswith("p="):
            policy = part[2:].lower()
    if policy in ("quarantine", "reject"):
        return CheckResult(PASS, f"DMARC policy is {policy}.", records)
    return CheckResult(WARN, "DMARC policy is 'none'; quarantine or reject is recommended.", records)


def check_ptr() -> CheckResult:
    """Forward-confirmed reverse DNS for the platform mail IP (shared by all domains)."""
    ip = settings.MAIL_IPV4
    if not ip:
        return CheckResult(UNKNOWN, "MAIL_IPV4 is not configured.")
    try:
        rev = dns.reversename.from_address(ip)
        ptrs = [str(r.target).rstrip(".").lower() for r in _query(str(rev), "PTR")]
    except (DNSLookupError, dns.exception.SyntaxError, ValueError) as exc:
        return CheckResult(UNKNOWN, str(exc))
    if settings.MAIL_HOSTNAME not in ptrs:
        return CheckResult(FAIL, f"PTR for {ip} must be {settings.MAIL_HOSTNAME}.", ptrs)
    try:
        forward = a_records(settings.MAIL_HOSTNAME)
    except DNSLookupError as exc:
        return CheckResult(UNKNOWN, str(exc), ptrs)
    if ip not in forward:
        return CheckResult(FAIL, f"{settings.MAIL_HOSTNAME} does not resolve back to {ip}.", ptrs)
    return CheckResult(PASS, "Forward-confirmed reverse DNS is correct.", ptrs)


def dnsbl_lookup(ip: str, zone: str) -> tuple[bool, str]:
    """Return (listed, response). Raises DNSLookupError on resolver failure."""
    octets = ip.split(".")
    if len(octets) != 4:
        raise DNSLookupError("Only IPv4 DNSBL lookups are supported.")
    query = ".".join(reversed(octets)) + "." + zone
    servers = settings.DNSBL_RESOLVERS or None
    answers = _query(query, "A", nameservers=servers if servers else [])
    codes = [r.address for r in answers]
    # Spamhaus returns 127.255.255.x when queried via public/open resolvers: not a listing.
    real = [c for c in codes if c.startswith("127.") and not c.startswith("127.255.255.")]
    if codes and not real:
        raise DNSLookupError(f"{zone} refused the query ({', '.join(codes)}); use a private resolver.")
    return bool(real), ", ".join(real)
