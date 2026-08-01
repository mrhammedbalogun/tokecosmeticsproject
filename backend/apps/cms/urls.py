from django.urls import path

from apps.cms.views import PublicPageDetailView, PublicPageListView

urlpatterns = [
    path("pages/", PublicPageListView.as_view(), name="cms-page-list"),
    path("pages/<slug:slug>/", PublicPageDetailView.as_view(), name="cms-page-detail"),
]
