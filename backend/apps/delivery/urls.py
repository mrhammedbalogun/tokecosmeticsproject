from django.urls import path

from apps.delivery.views import RegionBrowseView

urlpatterns = [
    path("regions/", RegionBrowseView.as_view(), name="region-browse"),
]
