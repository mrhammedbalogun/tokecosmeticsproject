"""Authenticated customer self-service under /api/v1/me/ (addresses now; wishlist in
Plan-11 Task 8). Profile GET/PATCH stays at /api/v1/auth/me/ (already shipped)."""
from django.urls import path

from apps.accounts.views import (
    AddressDetailView,
    AddressListCreateView,
    SetDefaultBillingView,
    SetDefaultShippingView,
)

urlpatterns = [
    path("addresses/", AddressListCreateView.as_view(), name="address-list"),
    path("addresses/<int:pk>/", AddressDetailView.as_view(), name="address-detail"),
    path("addresses/<int:pk>/set-default-shipping/",
         SetDefaultShippingView.as_view(), name="address-default-shipping"),
    path("addresses/<int:pk>/set-default-billing/",
         SetDefaultBillingView.as_view(), name="address-default-billing"),
]
