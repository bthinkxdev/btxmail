from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.accounts import views as account_views
from apps.audit.views import AuditLogViewSet
from apps.businesses.views import BusinessViewSet, DashboardView, PlanViewSet
from apps.core import views as core_views
from apps.domains.views import DomainViewSet
from apps.mailboxes.views import AliasViewSet, MailboxViewSet
from apps.monitoring import views as monitoring_views
from apps.notifications import views as notification_views
from apps.security.views import SecurityEventViewSet

router = DefaultRouter(trailing_slash=True)
router.include_root_view = False
router.register("users", account_views.UserViewSet, basename="user")
router.register("plans", PlanViewSet, basename="plan")
router.register("businesses", BusinessViewSet, basename="business")
router.register("domains", DomainViewSet, basename="domain")
router.register("mailboxes", MailboxViewSet, basename="mailbox")
router.register("aliases", AliasViewSet, basename="alias")
router.register("security-events", SecurityEventViewSet, basename="security-event")
router.register("audit-logs", AuditLogViewSet, basename="audit-log")
router.register("monitoring/alerts", monitoring_views.AlertViewSet, basename="alert")

auth_patterns = [
    path("csrf/", account_views.CsrfView.as_view(), name="auth-csrf"),
    path("login/", account_views.LoginView.as_view(), name="auth-login"),
    path("login/otp/", account_views.LoginOtpView.as_view(), name="auth-login-otp"),
    path("logout/", account_views.LogoutView.as_view(), name="auth-logout"),
    path("me/", account_views.MeView.as_view(), name="auth-me"),
    path("password/change/", account_views.PasswordChangeView.as_view(), name="auth-password-change"),
    path("password/reset/", account_views.PasswordResetRequestView.as_view(), name="auth-password-reset"),
    path(
        "password/reset/confirm/", account_views.PasswordResetConfirmView.as_view(), name="auth-password-reset-confirm"
    ),
    path("2fa/setup/", account_views.TwoFactorSetupView.as_view(), name="auth-2fa-setup"),
    path("2fa/enable/", account_views.TwoFactorEnableView.as_view(), name="auth-2fa-enable"),
    path("2fa/disable/", account_views.TwoFactorDisableView.as_view(), name="auth-2fa-disable"),
    path("2fa/recovery-codes/", account_views.RecoveryCodesView.as_view(), name="auth-2fa-recovery"),
]

api_patterns = [
    path("auth/", include(auth_patterns)),
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
    path("monitoring/reputation/", monitoring_views.ReputationView.as_view(), name="monitoring-reputation"),
    path("monitoring/run/", monitoring_views.RunChecksView.as_view(), name="monitoring-run"),
    path("monitoring/backup-report/", monitoring_views.BackupReportView.as_view(), name="monitoring-backup-report"),
    path("notifications/config/", notification_views.PushConfigView.as_view(), name="push-config"),
    path("notifications/preferences/", notification_views.PreferencesView.as_view(), name="push-preferences"),
    path("notifications/subscriptions/", notification_views.SubscriptionView.as_view(), name="push-subscriptions"),
    path("notifications/test/", notification_views.TestPushView.as_view(), name="push-test"),
    path("push/new-mail/", notification_views.NewMailHookView.as_view(), name="push-new-mail"),
    path("", include(router.urls)),
]

urlpatterns = [
    path("api/", include(api_patterns)),
    path("healthz", core_views.healthz, name="healthz"),
    path("readyz", core_views.readyz, name="readyz"),
    path("metrics", core_views.metrics, name="metrics"),
]

if settings.ADMIN_URL:
    urlpatterns.append(path(settings.ADMIN_URL, admin.site.urls))

admin.site.site_header = f"{settings.PLATFORM_NAME} — administration"
admin.site.site_title = settings.PLATFORM_NAME
