from django.urls import path

from apps.carts.views import CartItemDetailView, CartItemsView, CartView

urlpatterns = [
    path("cart/", CartView.as_view(), name="cart"),
    path("cart/items/", CartItemsView.as_view(), name="cart-items"),
    path("cart/items/<int:variant_id>/", CartItemDetailView.as_view(), name="cart-item-detail"),
]
