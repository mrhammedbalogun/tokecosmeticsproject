from django.urls import path

from apps.reviews.views import ProductReviewsView

urlpatterns = [
    path("products/<slug:slug>/reviews/", ProductReviewsView.as_view(), name="product-reviews"),
]
