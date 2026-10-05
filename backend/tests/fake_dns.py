"""In-memory DNS used in place of dnspython lookups."""

from dataclasses import dataclass


@dataclass
class TXT:
    value: str

    @property
    def strings(self):
        # DNS splits long TXT values into 255-byte chunks
        raw = self.value.encode()
        return [raw[i : i + 255] for i in range(0, len(raw), 255)] or [b""]


@dataclass
class MX:
    preference: int
    exchange: str


@dataclass
class A:
    address: str


@dataclass
class PTR:
    target: str


class FakeDNS:
    def __init__(self):
        self.records: dict[tuple[str, str], list] = {}
        self.broken: set[tuple[str, str]] = set()

    def set_txt(self, name, *values):
        self.records[(name.lower(), "TXT")] = [TXT(v) for v in values]

    def set_mx(self, name, *hosts):
        self.records[(name.lower(), "MX")] = [MX(10 * (i + 1), h + ".") for i, h in enumerate(hosts)]

    def set_a(self, name, *ips):
        self.records[(name.lower(), "A")] = [A(ip) for ip in ips]

    def set_ptr(self, name, target):
        self.records[(name.lower(), "PTR")] = [PTR(target + ".")]

    def query(self, name, rdtype, nameservers=None):
        from apps.domains.dns_checks import DNSLookupError

        key = (str(name).rstrip(".").lower(), rdtype)
        if key in self.broken:
            raise DNSLookupError(f"DNS timeout for {name} {rdtype}")
        return list(self.records.get(key, []))

    def publish_domain(
        self, domain, *, mail_host, dkim_txt=None, selector="dkim", spf="v=spf1 mx -all", dmarc="v=DMARC1; p=quarantine"
    ):
        """Publish a correct, complete DNS setup for a customer domain."""
        self.set_mx(domain, mail_host)
        self.set_txt(domain, spf, "google-site-verification=abc")
        if dmarc:
            self.set_txt(f"_dmarc.{domain}", dmarc)
        if dkim_txt:
            self.set_txt(f"{selector}._domainkey.{domain}", dkim_txt)
