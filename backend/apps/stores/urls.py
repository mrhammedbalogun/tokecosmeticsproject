from django.urls import path

from apps.stores.views import StoreListView, StorePlacesView

urlpatterns = [
    path("places/", StorePlacesView.as_view(), name="store-places"),
    path("", StoreListView.as_view(), name="store-list"),
]
