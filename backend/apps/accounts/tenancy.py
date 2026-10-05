from rest_framework.exceptions import NotFound, ValidationError

from apps.businesses.models import Business


def resolve_business(request, business_id=None) -> Business:
    """
    The business a write applies to.
    * Business admins: always their own business — any client-supplied id is ignored.
    * Platform staff: must name an existing business.
    """
    user = request.user
    if not user.is_platform_staff:
        return Business.objects.select_related("plan").get(pk=user.business_id)
    if business_id in (None, ""):
        raise ValidationError({"business": "This field is required."})
    try:
        return Business.objects.select_related("plan").get(pk=int(business_id))
    except (Business.DoesNotExist, ValueError, TypeError) as exc:
        raise NotFound("Business not found.") from exc
