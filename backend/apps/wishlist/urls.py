from django.urls import path

from apps.wishlist.views import WishlistItemDeleteView, WishlistView

urlpatterns = [
    path("wishlist/", WishlistView.as_view(), name="wishlist"),
    path("wishlist/<str:sku>/", WishlistItemDeleteView.as_view(), name="wishlist-item"),
]
