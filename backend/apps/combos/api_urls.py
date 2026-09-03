from django.urls import path

from apps.combos.api_views import ComboDetailView, ComboListView

urlpatterns = [
    path("combos/", ComboListView.as_view(), name="combo-list"),
    path("combos/<slug:slug>/", ComboDetailView.as_view(), name="combo-detail"),
]
