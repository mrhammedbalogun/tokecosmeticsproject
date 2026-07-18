"""Root URL configuration.

`/django-admin/` is the low-level Django admin fallback (IP-restricted in prod, Plan-02).
The versioned API lives under `/api/v1/`.
"""
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.core.views import healthz

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("healthz/", healthz),
    # API v1
    path("api/v1/auth/", include("apps.accounts.urls")),
    path("api/v1/me/", include("apps.accounts.me_urls")),
    path("api/v1/me/", include("apps.wishlist.urls")),
    path("api/v1/meta/", include("apps.core.urls")),
    path("api/v1/meta/", include("apps.delivery.urls")),
    path("api/v1/", include("apps.catalog.api_urls")),
    path("api/v1/", include("apps.search.urls")),
    path("api/v1/", include("apps.carts.urls")),
    path("api/v1/", include("apps.checkout.urls")),
    path("api/v1/", include("apps.payments.urls")),
    path("api/v1/", include("apps.orders.urls")),
    path("api/v1/admin/", include("apps.catalog.admin_urls")),
    path("api/v1/admin/", include("apps.inventory.admin_urls")),
    path("api/v1/admin/", include("apps.payments.admin_urls")),
    path("api/v1/admin/", include("apps.orders.admin_urls")),
    path("api/v1/admin/", include("apps.shipping.admin_urls")),
    # OpenAPI schema + docs
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]
