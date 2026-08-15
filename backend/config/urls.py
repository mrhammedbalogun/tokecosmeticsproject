"""Root URL configuration. The versioned API lives under `/api/v1/`.

`/django-admin/` is the low-level Django admin fallback. **In production it is DENIED
OUTRIGHT at the web server**, not IP-restricted: the live Apache vhost carries
`<Location /django-admin/> Require all denied`, verified 2026-07-28 as a 403 from the
public internet. The previous wording here said "IP-restricted in prod", which described
a control that does not exist — this project has been bitten three times by comments
asserting controls nobody built, so the rule now is that a comment describes what is
configured TODAY and aspirations go in a runbook as tracked TODOs.

That denial is configuration and cannot be asserted from the test suite. What the suite
DOES assert (`apps/accounts/tests/test_admin_surface_guard.py`) is the property that
makes a Django admin session harmless to the API even if the vhost rule were ever
removed: no DRF view anywhere accepts `SessionAuthentication`, so a Django login cookie
authenticates nothing under `/api/v1/`. Without that, a session cookie would bypass the
admin audience claim entirely, since a session cannot carry one.
"""
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.core.views import healthz
from apps.delivery.views import GigWebhookView

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("healthz/", healthz),
    # API v1
    path("api/v1/auth/", include("apps.accounts.urls")),
    path("api/v1/me/", include("apps.accounts.me_urls")),
    path("api/v1/me/", include("apps.wishlist.urls")),
    path("api/v1/me/", include("apps.referrals.urls")),
    path("api/v1/referrals/", include("apps.referrals.public_urls")),
    path("api/v1/meta/", include("apps.core.urls")),
    path("api/v1/meta/", include("apps.delivery.urls")),
    path("api/v1/", include("apps.catalog.api_urls")),
    path("api/v1/", include("apps.reviews.urls")),
    path("api/v1/", include("apps.newsletter.urls")),
    path("api/v1/", include("apps.search.urls")),
    path("api/v1/", include("apps.carts.urls")),
    path("api/v1/", include("apps.checkout.urls")),
    # MUST precede payments.urls: its `webhooks/<str:gateway>/` would otherwise
    # swallow /webhooks/gig/ and 404 it as an unknown payment gateway.
    path("api/v1/webhooks/gig/", GigWebhookView.as_view(), name="gig-webhook"),
    path("api/v1/", include("apps.payments.urls")),
    path("api/v1/", include("apps.orders.urls")),
    path("api/v1/cms/", include("apps.cms.urls")),
    path("api/v1/admin/", include("apps.accounts.admin_urls")),
    path("api/v1/admin/", include("apps.core.admin_urls")),
    path("api/v1/admin/", include("apps.catalog.admin_urls")),
    path("api/v1/admin/", include("apps.cms.admin_urls")),
    path("api/v1/admin/", include("apps.inventory.admin_urls")),
    path("api/v1/admin/", include("apps.payments.admin_urls")),
    path("api/v1/admin/", include("apps.checkout.admin_urls")),
    path("api/v1/admin/", include("apps.delivery.admin_urls")),
    path("api/v1/admin/", include("apps.analytics.admin_urls")),
    path("api/v1/admin/", include("apps.orders.admin_urls")),
    path("api/v1/admin/", include("apps.shipping.admin_urls")),
    path("api/v1/admin/", include("apps.reviews.admin_urls")),
    # OpenAPI schema + docs
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]

# DEV ONLY: serve uploaded media (seeded product/category images) from runserver.
# django.conf.urls.static.static() is a no-op when DEBUG is False, so this cannot
# change production behaviour. Prod media is served by the web server/CDN (Plan-22).
from django.conf import settings  # noqa: E402
from django.conf.urls.static import static  # noqa: E402

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
