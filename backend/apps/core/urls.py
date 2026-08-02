from django.urls import path

from apps.core.redirects import PublicRedirectView
from apps.core.views import CountryListView

urlpatterns = [
    path("countries/", CountryListView.as_view(), name="meta-countries"),
    # Called by the storefront's root catch-all on what would otherwise be a 404.
    path("redirect/", PublicRedirectView.as_view(), name="meta-redirect"),
]
