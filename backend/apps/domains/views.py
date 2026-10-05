from django.db.models import Q
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.accounts.permissions import IsFullyAuthenticated, scope_queryset
from apps.accounts.tenancy import resolve_business
from apps.accounts.throttles import SensitiveActionThrottle

from . import services
from .models import Domain
from .serializers import DomainCreateSerializer, DomainDNSStatusSerializer, DomainSerializer, ReasonSerializer


def domain_queryset(user):
    return scope_queryset(Domain.objects.select_related("business", "dns_status"), user)


def create_domain_response(request, business_id=None):
    data = DomainCreateSerializer(data=request.data)
    data.is_valid(raise_exception=True)
    business = resolve_business(
        request, business_id if business_id is not None else data.validated_data.get("business")
    )
    domain = services.create_domain(
        business=business, name=data.validated_data["name"], actor=request.user, request=request
    )
    domain = Domain.objects.select_related("business", "dns_status").get(pk=domain.pk)
    return Response(DomainSerializer(domain).data, status=status.HTTP_201_CREATED)


class DomainViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet
):
    serializer_class = DomainSerializer
    permission_classes = [IsFullyAuthenticated]

    def get_queryset(self):
        qs = domain_queryset(self.request.user)
        params = self.request.query_params
        if params.get("business") and self.request.user.is_platform_staff:
            qs = qs.filter(business_id=params["business"])
        if params.get("status"):
            qs = qs.filter(status=params["status"])
        if params.get("search"):
            term = params["search"].strip()
            qs = qs.filter(Q(name__icontains=term) | Q(business__name__icontains=term))
        return qs.order_by("name")

    def _staff_only(self):
        if not self.request.user.is_platform_staff:
            raise PermissionDenied("Only platform administrators can do this.")

    def create(self, request):
        return create_domain_response(request)

    def destroy(self, request, pk=None):
        services.delete_domain(self.get_object(), actor=request.user, request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"], throttle_classes=[SensitiveActionThrottle])
    def verify(self, request, pk=None):
        domain = self.get_object()
        if domain.status == Domain.Status.PENDING_VERIFICATION and services.verification_expired(domain):
            return Response(
                {"detail": "The verification window expired. Generate a new token.", "code": "verification_expired"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        result = services.verify_domain(domain, actor=request.user, request=request)
        domain.refresh_from_db()
        return Response({"result": result.as_dict(), "domain": DomainSerializer(domain).data})

    @action(detail=True, methods=["post"], url_path="regenerate-token")
    def regenerate_token(self, request, pk=None):
        domain = services.regenerate_verification_token(self.get_object(), actor=request.user, request=request)
        return Response(DomainSerializer(domain).data)

    @action(detail=True, methods=["get"], url_path="dns-status")
    def dns_status(self, request, pk=None):
        domain = self.get_object()
        status_obj = getattr(domain, "dns_status", None)
        return Response(
            {
                "domain": domain.name,
                "status": domain.status,
                "records": domain.required_dns_records(),
                "checks": DomainDNSStatusSerializer(status_obj).data if status_obj else None,
            }
        )

    @action(detail=True, methods=["post"], url_path="check-dns", throttle_classes=[SensitiveActionThrottle])
    def check_dns(self, request, pk=None):
        domain = self.get_object()
        if not domain.mailcow_provisioned:
            return Response(
                {"detail": "Verify the domain first.", "code": "not_provisioned"}, status=status.HTTP_400_BAD_REQUEST
            )
        services.refresh_dns_status(domain)
        domain = Domain.objects.select_related("business", "dns_status").get(pk=domain.pk)
        return Response(DomainSerializer(domain).data)

    @action(detail=True, methods=["post"], url_path="verify-manually")
    def verify_manually(self, request, pk=None):
        self._staff_only()
        data = ReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        domain = services.mark_verified_manually(
            self.get_object(), actor=request.user, request=request, reason=data.validated_data["reason"]
        )
        return Response(DomainSerializer(domain).data)

    @action(detail=True, methods=["post"], url_path="retry-provisioning")
    def retry_provisioning(self, request, pk=None):
        self._staff_only()
        domain = services.retry_provisioning(self.get_object(), actor=request.user, request=request)
        return Response(DomainSerializer(domain).data)

    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None):
        self._staff_only()
        domain = services.set_domain_suspended(self.get_object(), True, actor=request.user, request=request)
        return Response(DomainSerializer(domain).data)

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        self._staff_only()
        domain = services.set_domain_suspended(self.get_object(), False, actor=request.user, request=request)
        return Response(DomainSerializer(domain).data)

    # Nested routes from the API design: /api/domains/{id}/mailboxes/ and /aliases/
    @action(detail=True, methods=["get", "post"])
    def mailboxes(self, request, pk=None):
        from apps.mailboxes.views import create_mailbox_response, list_mailboxes_response

        domain = self.get_object()
        if request.method == "POST":
            return create_mailbox_response(request, domain=domain)
        return list_mailboxes_response(self, request, domain=domain)

    @action(detail=True, methods=["get", "post"])
    def aliases(self, request, pk=None):
        from apps.mailboxes.views import create_alias_response, list_aliases_response

        domain = self.get_object()
        if request.method == "POST":
            return create_alias_response(request, domain=domain)
        return list_aliases_response(self, request, domain=domain)
