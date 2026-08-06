from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import Product
from apps.orders.models import Order
from apps.reviews.models import Review
from apps.reviews.serializers import ReviewReadSerializer, ReviewWriteSerializer
from apps.reviews.services import recompute_product_rating

# Statuses that make a purchase "verified" — the customer has the goods in hand.
# completed = delivered + return window elapsed (set by complete_delivered_orders).
_VERIFIED_STATUSES = ("delivered", "completed")


def _verified_order(user, product):
    """The most recent delivered/completed order of this user that contains the product,
    or None. Used both as the permission gate and to stamp Review.order for audit."""
    return (
        Order.objects.filter(
            user=user, status__in=_VERIFIED_STATUSES, items__variant__product=product
        )
        .order_by("-placed_at")
        .first()
    )


class ReviewEligibilityView(APIView):
    """Answers "may I review this product?" for the signed-in customer, so the
    storefront can pick which state to render (form / already-reviewed / not a
    purchaser) instead of showing every visitor a form that 403s on submit."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, slug):
        product = get_object_or_404(Product, slug=slug)
        existing = Review.objects.filter(product=product, user=request.user).first()
        return Response(
            {
                "has_reviewed": existing is not None,
                # Exposed so the UI can say "awaiting approval" for a pending review.
                "review_status": existing.status if existing else None,
                "eligible": existing is None
                and _verified_order(request.user, product) is not None,
            }
        )


class ProductReviewsView(APIView):
    def get_permissions(self):
        # Public GET, authenticated POST.
        if self.request.method == "POST":
            return [permissions.IsAuthenticated()]
        return [permissions.AllowAny()]

    def get(self, request, slug):
        product = get_object_or_404(Product, slug=slug)
        reviews = product.reviews.filter(status="approved").select_related("user")
        return Response(ReviewReadSerializer(reviews, many=True).data)

    def post(self, request, slug):
        product = get_object_or_404(Product, slug=slug)
        order = _verified_order(request.user, product)
        if order is None:
            return Response(
                {"detail": "Only verified purchasers can review this product."},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = ReviewWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            review = Review.objects.create(
                product=product, user=request.user, order=order,
                **serializer.validated_data,
            )
        except IntegrityError:
            # unique_together(product, user): they already reviewed it.
            return Response(
                {"detail": "You have already reviewed this product."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Reviews are live on creation (no pre-moderation), so the new rating must be
        # in the denormalised fields before the storefront re-renders the product.
        recompute_product_rating(product)
        return Response(ReviewReadSerializer(review).data, status=status.HTTP_201_CREATED)
