from django.urls import path

from apps.cms.views import (
    PublicHomepageView,
    PublicMenuView,
    PublicPageDetailView,
    PublicPageListView,
)

urlpatterns = [
    path("homepage/", PublicHomepageView.as_view(), name="cms-homepage"),
    path("menus/", PublicMenuView.as_view(), name="cms-menus"),
    path("pages/", PublicPageListView.as_view(), name="cms-page-list"),
    path("pages/<slug:slug>/", PublicPageDetailView.as_view(), name="cms-page-detail"),
]
