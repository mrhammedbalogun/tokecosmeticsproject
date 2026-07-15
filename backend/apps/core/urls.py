from django.urls import path

from apps.core.views import CountryListView

urlpatterns = [
    path("countries/", CountryListView.as_view(), name="meta-countries"),
]
