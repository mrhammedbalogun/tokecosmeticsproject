from django.urls import path

from apps.reviews.views import ProductReviewsView, ReviewEligibilityView

urlpatterns = [
    path("products/<slug:slug>/reviews/", ProductReviewsView.as_view(), name="product-reviews"),
    path(
        "products/<slug:slug>/reviews/eligibility/",
        ReviewEligibilityView.as_view(),
        name="product-review-eligibility",
    ),
]
