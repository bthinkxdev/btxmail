import ipaddress

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.http import HttpResponseForbidden, JsonResponse
from django.views.decorators.http import require_GET
from django_prometheus.exports import ExportToDjangoView


@require_GET
def healthz(request):
    """Liveness: the process is up."""
    return JsonResponse({"status": "ok"})


@require_GET
def readyz(request):
    """Readiness: database and cache are reachable."""
    checks = {}
    ok = True
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        checks["database"] = "ok"
    except Exception:  # noqa: BLE001
        checks["database"] = "error"
        ok = False
    try:
        cache.set("readyz", "1", 5)
        checks["cache"] = "ok" if cache.get("readyz") == "1" else "error"
        ok = ok and checks["cache"] == "ok"
    except Exception:  # noqa: BLE001
        checks["cache"] = "error"
        ok = False
    return JsonResponse({"status": "ok" if ok else "error", "checks": checks}, status=200 if ok else 503)


def _ip_allowed(remote: str) -> bool:
    try:
        addr = ipaddress.ip_address(remote)
    except ValueError:
        return False
    for entry in settings.METRICS_ALLOWED_IPS:
        if entry == "*":
            return True
        try:
            if addr in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            continue
    return False


@require_GET
def metrics(request):
    """
    Prometheus metrics. Only reachable from allow-listed networks (the public
    nginx also refuses /metrics), and never via a forwarded request.
    """
    if request.META.get("HTTP_X_FORWARDED_FOR") or not _ip_allowed(request.META.get("REMOTE_ADDR", "")):
        return HttpResponseForbidden("forbidden")
    return ExportToDjangoView(request)
