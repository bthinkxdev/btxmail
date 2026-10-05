import contextvars
import logging
import re
import uuid

_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
_VALID_ID = re.compile(r"^[A-Za-z0-9\-]{8,64}$")


def get_request_id() -> str:
    return _request_id.get()


class RequestIdMiddleware:
    """Attach a request id to every request/response and to log records."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        incoming = request.META.get("HTTP_X_REQUEST_ID", "")
        request_id = incoming if _VALID_ID.match(incoming) else uuid.uuid4().hex
        token = _request_id.set(request_id)
        request.request_id = request_id
        try:
            response = self.get_response(request)
        finally:
            _request_id.reset(token)
        response["X-Request-ID"] = request_id
        return response


class RequestIdLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()
        return True
