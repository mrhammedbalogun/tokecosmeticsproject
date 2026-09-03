from django.urls import path

from apps.carts.views import (
    CartComboDetailView,
    CartCombosView,
    CartItemDetailView,
    CartItemsView,
    CartMergeView,
    CartView,
)

urlpatterns = [
    path("cart/", CartView.as_view(), name="cart"),
    path("cart/items/", CartItemsView.as_view(), name="cart-items"),
    path("cart/items/<int:variant_id>/", CartItemDetailView.as_view(), name="cart-item-detail"),
    # Combos are addressed by GROUP id, not by combo slug: the same bundle could in
    # principle be held twice (it cannot today — `add_combo` merges — but an id does not
    # depend on that staying true, and a slug would).
    path("cart/combos/", CartCombosView.as_view(), name="cart-combos"),
    path("cart/combos/<int:group_id>/", CartComboDetailView.as_view(), name="cart-combo-detail"),
    path("cart/merge/", CartMergeView.as_view(), name="cart-merge"),
]
