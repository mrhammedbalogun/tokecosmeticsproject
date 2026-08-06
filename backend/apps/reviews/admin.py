from django.contrib import admin

from apps.reviews.models import Review
from apps.reviews.services import recompute_product_rating


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    """Backstop moderation. The everyday surface is the admin portal's Reviews screen
    (ProductReviewAdminViewSet); this stays for emergencies and bulk sweeps."""

    list_display = ("product", "user", "rating", "status", "created_at")
    list_filter = ("status", "rating")
    search_fields = ("product__name", "user__email", "body")
    readonly_fields = ("product", "user", "order", "rating", "title", "body", "created_at")
    actions = ["hide_reviews", "unhide_reviews"]

    def _set_status(self, queryset, status: str) -> None:
        products = set()
        for review in queryset:
            review.status = status
            review.save(update_fields=["status", "updated_at"])
            products.add(review.product)
        # Either direction moves a review in or out of the average.
        for product in products:
            recompute_product_rating(product)

    @admin.action(description="Hide selected reviews from the public")
    def hide_reviews(self, request, queryset):
        self._set_status(queryset, "hidden")

    @admin.action(description="Unhide selected reviews")
    def unhide_reviews(self, request, queryset):
        self._set_status(queryset, "approved")
