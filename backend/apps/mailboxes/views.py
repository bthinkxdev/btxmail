from django.db.models import Q
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.accounts.permissions import IsFullyAuthenticated, scope_queryset
from apps.accounts.throttles import SensitiveActionThrottle
from apps.domains.models import Domain

from . import services
from .models import Alias, Mailbox
from .serializers import (
    AliasCreateSerializer,
    AliasSerializer,
    AliasUpdateSerializer,
    MailboxCreateSerializer,
    MailboxSerializer,
    MailboxUpdateSerializer,
    ReasonSerializer,
)


def _scoped_domain(request, domain_id) -> Domain:
    """Look the domain up inside the caller's tenant scope (404 otherwise — no existence leak)."""
    if domain_id in (None, ""):
        raise ValidationError({"domain": "This field is required."})
    try:
        return scope_queryset(Domain.objects.select_related("business__plan"), request.user).get(pk=int(domain_id))
    except (Domain.DoesNotExist, ValueError, TypeError) as exc:
        raise NotFound("Domain not found.") from exc


def mailbox_queryset(user):
    return scope_queryset(Mailbox.objects.select_related("business__plan", "domain"), user)


def alias_queryset(user):
    return scope_queryset(Alias.objects.select_related("business", "domain"), user)


def _paginate(view, request, qs, serializer_cls):
    page = view.paginate_queryset(qs)
    if page is not None:
        return view.get_paginated_response(serializer_cls(page, many=True).data)
    return Response(serializer_cls(qs, many=True).data)


# --------------------------------------------------------------------------- #
def create_mailbox_response(request, domain=None):
    data = MailboxCreateSerializer(data=request.data)
    data.is_valid(raise_exception=True)
    domain = domain or _scoped_domain(request, data.validated_data.get("domain"))
    mailbox, password = services.create_mailbox(
        business=domain.business,
        domain=domain,
        local_part=data.validated_data["local_part"],
        display_name=data.validated_data.get("display_name", ""),
        quota_mb=data.validated_data.get("quota_mb"),
        actor=request.user,
        request=request,
    )
    payload = MailboxSerializer(mailbox).data
    payload["temporary_password"] = password  # shown once, never stored
    response = Response(payload, status=status.HTTP_201_CREATED)
    response["Cache-Control"] = "no-store"
    return response


def list_mailboxes_response(view, request, domain):
    qs = mailbox_queryset(request.user).filter(domain=domain).order_by("email")
    return _paginate(view, request, qs, MailboxSerializer)


def create_alias_response(request, domain=None):
    data = AliasCreateSerializer(data=request.data)
    data.is_valid(raise_exception=True)
    domain = domain or _scoped_domain(request, data.validated_data.get("domain"))
    alias = services.create_alias(
        business=domain.business,
        domain=domain,
        local_part=data.validated_data["local_part"],
        destinations=data.validated_data["destinations"],
        actor=request.user,
        request=request,
    )
    return Response(AliasSerializer(alias).data, status=status.HTTP_201_CREATED)


def list_aliases_response(view, request, domain):
    qs = alias_queryset(request.user).filter(domain=domain).order_by("source_address")
    return _paginate(view, request, qs, AliasSerializer)


# --------------------------------------------------------------------------- #
class MailboxViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet
):
    serializer_class = MailboxSerializer
    permission_classes = [IsFullyAuthenticated]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        qs = mailbox_queryset(self.request.user)
        p = self.request.query_params
        if p.get("domain"):
            qs = qs.filter(domain_id=p["domain"])
        if p.get("business") and self.request.user.is_platform_staff:
            qs = qs.filter(business_id=p["business"])
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        if p.get("outbound_suspended") in ("true", "1"):
            qs = qs.filter(outbound_suspended=True)
        if p.get("search"):
            term = p["search"].strip()
            qs = qs.filter(Q(email__icontains=term) | Q(display_name__icontains=term))
        return qs.order_by("email")

    def get_throttles(self):
        if self.action in ("create", "reset_password"):
            return [SensitiveActionThrottle()]
        return super().get_throttles()

    def create(self, request):
        return create_mailbox_response(request)

    def partial_update(self, request, pk=None):
        mailbox = self.get_object()
        data = MailboxUpdateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        vd = data.validated_data
        limits_supplied = "outbound_limit_per_hour" in vd or "outbound_limit_per_day" in vd
        if limits_supplied and not request.user.is_platform_staff:
            raise PermissionDenied("Only platform administrators can change outbound limits.")
        mailbox = services.update_mailbox(
            mailbox,
            actor=request.user,
            request=request,
            display_name=vd.get("display_name"),
            quota_mb=vd.get("quota_mb"),
            outbound_limit_per_hour=vd.get("outbound_limit_per_hour", mailbox.outbound_limit_per_hour),
            outbound_limit_per_day=vd.get("outbound_limit_per_day", mailbox.outbound_limit_per_day),
            limits_supplied=limits_supplied,
        )
        return Response(MailboxSerializer(mailbox).data)

    def destroy(self, request, pk=None):
        services.delete_mailbox(self.get_object(), actor=request.user, request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _set_status(self, request, new_status):
        data = ReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        mailbox = services.set_mailbox_status(
            self.get_object(), new_status, actor=request.user, request=request, reason=data.validated_data["reason"]
        )
        return Response(MailboxSerializer(mailbox).data)

    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None):
        return self._set_status(request, Mailbox.Status.SUSPENDED)

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        return self._set_status(request, Mailbox.Status.ACTIVE)

    @action(detail=True, methods=["post"])
    def disable(self, request, pk=None):
        return self._set_status(request, Mailbox.Status.DISABLED)

    @action(detail=True, methods=["post"], url_path="reset-password")
    def reset_password(self, request, pk=None):
        password = services.reset_password(self.get_object(), actor=request.user, request=request)
        response = Response({"temporary_password": password})
        response["Cache-Control"] = "no-store"
        return response

    @action(detail=True, methods=["post"], url_path="suspend-outbound")
    def suspend_outbound(self, request, pk=None):
        data = ReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        reason = data.validated_data["reason"] or "Suspended manually by administrator"
        mailbox = services.suspend_outbound(self.get_object(), reason=reason, actor=request.user, request=request)
        return Response(MailboxSerializer(mailbox).data)

    @action(detail=True, methods=["post"], url_path="restore-outbound")
    def restore_outbound(self, request, pk=None):
        if not request.user.is_platform_staff:
            raise PermissionDenied("Outbound mail can only be restored by BThinkX support after review.")
        data = ReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        mailbox = services.restore_outbound(
            self.get_object(), actor=request.user, request=request, note=data.validated_data["reason"]
        )
        return Response(MailboxSerializer(mailbox).data)


class AliasViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    serializer_class = AliasSerializer
    permission_classes = [IsFullyAuthenticated]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        qs = alias_queryset(self.request.user)
        p = self.request.query_params
        if p.get("domain"):
            qs = qs.filter(domain_id=p["domain"])
        if p.get("business") and self.request.user.is_platform_staff:
            qs = qs.filter(business_id=p["business"])
        if p.get("search"):
            qs = qs.filter(source_address__icontains=p["search"].strip())
        return qs.order_by("source_address")

    def create(self, request):
        return create_alias_response(request)

    def partial_update(self, request, pk=None):
        data = AliasUpdateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        alias = services.update_alias(
            self.get_object(),
            actor=request.user,
            request=request,
            destinations=data.validated_data.get("destinations"),
            status=data.validated_data.get("status"),
        )
        return Response(AliasSerializer(alias).data)

    def destroy(self, request, pk=None):
        services.delete_alias(self.get_object(), actor=request.user, request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)
