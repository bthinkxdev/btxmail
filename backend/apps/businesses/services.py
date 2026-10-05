from django.db import transaction

from apps.audit import service as audit
from apps.core.exceptions import ServiceError

from .models import Business


def create_business(*, actor, request=None, **fields) -> Business:
    business = Business.objects.create(**fields)
    audit.record(
        "business.created",
        actor=actor,
        request=request,
        business=business,
        obj=business,
        metadata={"plan": business.plan.code},
    )
    return business


def update_business(business: Business, *, actor, request=None, **fields) -> Business:
    plan_changed = "plan" in fields and fields["plan"].pk != business.plan_id
    if plan_changed:
        new_plan = fields["plan"]
        active_mailboxes = business.mailboxes.exclude(status="DELETING")
        if active_mailboxes.count() > new_plan.max_mailboxes:
            raise ServiceError("The business has more mailboxes than the new plan allows.")
        if business.domains.exclude(status="DELETING").count() > new_plan.max_domains:
            raise ServiceError("The business has more domains than the new plan allows.")
        if business.allocated_storage_mb() > new_plan.total_storage_mb:
            raise ServiceError("Allocated mailbox storage exceeds the new plan's total storage.")
        if active_mailboxes.filter(quota_mb__gt=new_plan.max_mailbox_quota_mb).exists():
            raise ServiceError("Some mailboxes have a larger quota than the new plan allows per mailbox.")
        if business.aliases.count() > new_plan.max_aliases:
            raise ServiceError("The business has more aliases than the new plan allows.")

    changed = {}
    for key, value in fields.items():
        if getattr(business, key) != value:
            changed[key] = value.code if key == "plan" else value
            setattr(business, key, value)
    if not changed:
        return business
    business.save()
    audit.record("business.updated", actor=actor, request=request, business=business, obj=business, metadata=changed)

    if plan_changed:
        from apps.domains.tasks import apply_plan_limits_task
        from apps.mailboxes.tasks import push_rate_limits_task

        transaction.on_commit(lambda: apply_plan_limits_task.delay(business.pk))
        transaction.on_commit(lambda: push_rate_limits_task.delay(business.pk))
    return business


def set_business_status(business: Business, status: str, *, actor, request=None, reason: str = "") -> Business:
    if status not in Business.Status.values:
        raise ServiceError("Invalid status.")
    if business.status == status:
        return business
    previous = business.status
    business.status = status
    business.suspended_reason = reason[:255] if status != Business.Status.ACTIVE else ""
    business.save(update_fields=["status", "suspended_reason", "updated_at"])
    audit.record(
        "business.status_changed",
        actor=actor,
        request=request,
        business=business,
        obj=business,
        metadata={"from": previous, "to": status, "reason": reason},
    )
    from apps.mailboxes.tasks import apply_business_state_task

    transaction.on_commit(lambda: apply_business_state_task.delay(business.pk))
    return business
