from django.db.models import Q, Sum
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsFullyAuthenticated, IsSuperAdmin, scope_queryset
from apps.audit import service as audit
from apps.domains.models import Domain
from apps.mailboxes.models import Mailbox
from apps.security.models import SecurityEvent

from . import services
from .models import Business, Plan
from .serializers import BusinessSerializer, BusinessStatusSerializer, PlanSerializer


class PlanViewSet(viewsets.ModelViewSet):
    serializer_class = PlanSerializer
    queryset = Plan.objects.all()
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [IsFullyAuthenticated()]
        return [IsSuperAdmin()]

    def get_queryset(self):
        user = self.request.user
        if user.is_platform_staff:
            return Plan.objects.all()
        return Plan.objects.filter(pk=user.business.plan_id)

    def perform_create(self, serializer):
        plan = serializer.save()
        audit.record("plan.created", request=self.request, obj=plan)

    def perform_update(self, serializer):
        plan = serializer.save()
        audit.record("plan.updated", request=self.request, obj=plan, metadata=dict(serializer.validated_data))
        from apps.domains.tasks import apply_plan_limits_task
        from apps.mailboxes.tasks import push_rate_limits_task

        for business_id in plan.businesses.values_list("pk", flat=True):
            apply_plan_limits_task.delay(business_id)
            push_rate_limits_task.delay(business_id)

    def destroy(self, request, *args, **kwargs):
        plan = self.get_object()
        if plan.businesses.exists():
            return Response(
                {"detail": "Plan is in use; deactivate it instead.", "code": "in_use"}, status=status.HTTP_409_CONFLICT
            )
        audit.record("plan.deleted", request=request, metadata={"code": plan.code})
        plan.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class BusinessViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = BusinessSerializer
    permission_classes = [IsFullyAuthenticated]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        user = self.request.user
        qs = Business.objects.select_related("plan")
        if not user.is_platform_staff:
            qs = qs.filter(pk=user.business_id)
        params = self.request.query_params
        if params.get("status"):
            qs = qs.filter(status=params["status"])
        if params.get("search"):
            term = params["search"].strip()
            qs = qs.filter(Q(name__icontains=term) | Q(legal_name__icontains=term) | Q(contact_email__icontains=term))
        return qs.order_by("name")

    def _require_staff(self):
        if not self.request.user.is_platform_staff:
            raise PermissionDenied("Only platform administrators can manage businesses.")

    def create(self, request, *args, **kwargs):
        self._require_staff()
        return super().create(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        self._require_staff()
        return super().partial_update(request, *args, **kwargs)

    def perform_create(self, serializer):
        serializer.instance = services.create_business(
            actor=self.request.user, request=self.request, **serializer.validated_data
        )

    def perform_update(self, serializer):
        serializer.instance = services.update_business(
            serializer.instance, actor=self.request.user, request=self.request, **serializer.validated_data
        )

    @action(detail=True, methods=["get", "post"])
    def domains(self, request, pk=None):
        """Nested route from the API design: /api/businesses/{id}/domains/."""
        from apps.domains.serializers import DomainSerializer
        from apps.domains.views import create_domain_response, domain_queryset

        business = self.get_object()
        if request.method == "POST":
            return create_domain_response(request, business_id=business.pk)
        qs = domain_queryset(request.user).filter(business=business).order_by("name")
        page = self.paginate_queryset(qs)
        return self.get_paginated_response(DomainSerializer(page, many=True).data)

    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None):
        self._require_staff()
        data = BusinessStatusSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        business = services.set_business_status(
            self.get_object(),
            Business.Status.SUSPENDED,
            actor=request.user,
            request=request,
            reason=data.validated_data["reason"],
        )
        return Response(BusinessSerializer(business).data)

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        self._require_staff()
        business = services.set_business_status(
            self.get_object(), Business.Status.ACTIVE, actor=request.user, request=request
        )
        return Response(BusinessSerializer(business).data)


class DashboardView(APIView):
    permission_classes = [IsFullyAuthenticated]

    def get(self, request):
        user = request.user
        domains = scope_queryset(Domain.objects.all(), user)
        mailboxes = scope_queryset(Mailbox.objects.exclude(status=Mailbox.Status.DELETING), user)
        events = scope_queryset(SecurityEvent.objects.filter(resolved_at__isnull=True), user)

        agg = mailboxes.aggregate(alloc=Sum("quota_mb"), used=Sum("used_bytes"))
        data = {
            "domains": {
                "total": domains.count(),
                "active": domains.filter(status=Domain.Status.ACTIVE).count(),
                "pending": domains.exclude(status__in=[Domain.Status.ACTIVE, Domain.Status.SUSPENDED]).count(),
            },
            "mailboxes": {
                "total": mailboxes.count(),
                "active": mailboxes.filter(status=Mailbox.Status.ACTIVE).count(),
                "suspended": mailboxes.filter(status=Mailbox.Status.SUSPENDED).count(),
                "outbound_suspended": mailboxes.filter(outbound_suspended=True).count(),
            },
            "storage": {"allocated_mb": agg["alloc"] or 0, "used_bytes": agg["used"] or 0},
            "open_security_events": events.count(),
            "recent_security_events": [
                {
                    "id": e.id,
                    "event_type": e.event_type,
                    "severity": e.severity,
                    "subject": e.subject,
                    "description": e.description,
                    "detected_at": e.detected_at,
                    "action_taken": e.action_taken,
                }
                for e in events.order_by("-detected_at")[:5]
            ],
        }
        if user.is_platform_staff:
            data["businesses"] = {
                "total": Business.objects.count(),
                "active": Business.objects.filter(status=Business.Status.ACTIVE).count(),
                "suspended": Business.objects.filter(status=Business.Status.SUSPENDED).count(),
            }
        else:
            business = user.business
            plan = business.plan
            data["business"] = {
                "id": business.id,
                "name": business.name,
                "status": business.status,
                "plan": PlanSerializer(plan).data,
                "limits": {
                    "domains": plan.max_domains,
                    "mailboxes": plan.max_mailboxes,
                    "storage_mb": plan.total_storage_mb,
                    "aliases": plan.max_aliases,
                },
                "aliases": business.aliases.count(),
            }
        return Response(data)
