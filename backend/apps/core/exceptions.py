import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler

from apps.core.middleware import get_request_id

logger = logging.getLogger(__name__)


class ServiceError(APIException):
    """Business-rule violation raised by service-layer code."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "The request could not be completed."
    default_code = "service_error"


class QuotaExceeded(ServiceError):
    status_code = status.HTTP_409_CONFLICT
    default_code = "quota_exceeded"


class Conflict(ServiceError):
    status_code = status.HTTP_409_CONFLICT
    default_code = "conflict"


class UpstreamError(APIException):
    """The mail infrastructure rejected or failed the operation."""

    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "The mail server could not complete the operation. Please retry shortly."
    default_code = "upstream_error"


def api_exception_handler(exc, context):
    from apps.mailcow.errors import to_api_error
    from apps.mailcow.exceptions import MailcowError

    if isinstance(exc, DjangoValidationError):
        exc = ValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages)
    elif isinstance(exc, MailcowError):
        exc = to_api_error(exc)

    response = exception_handler(exc, context)
    if response is None:
        logger.exception("Unhandled API error", exc_info=exc)
        return Response(
            {"detail": "Internal server error.", "code": "server_error", "request_id": get_request_id()},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    data = response.data
    if isinstance(data, dict) and "detail" in data:
        code = getattr(exc, "default_code", None)
        detail = data["detail"]
        code = getattr(detail, "code", code)
        response.data = {"detail": str(detail), "code": code or "error"}
    else:
        response.data = {"detail": "Validation failed.", "code": "invalid", "errors": data}
    response.data["request_id"] = get_request_id()
    return response
