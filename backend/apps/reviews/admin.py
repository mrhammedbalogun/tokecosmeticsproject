from django.contrib import admin

from apps.reviews.models import Review
from apps.reviews.services import recompute_product_rating


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ("product", "user", "rating", "status", "created_at")
    list_filter = ("status", "rating")
    search_fields = ("product__name", "user__email", "body")
    readonly_fields = ("product", "user", "order", "rating", "title", "body", "created_at")
    actions = ["approve_reviews", "reject_reviews"]

    @admin.action(description="Approve selected reviews")
    def approve_reviews(self, request, queryset):
        products = set()
        for review in queryset:
            review.status = "approved"
            review.save(update_fields=["status", "updated_at"])
            products.add(review.product)
        for product in products:
            recompute_product_rating(product)

    @admin.action(description="Reject selected reviews")
    def reject_reviews(self, request, queryset):
        products = set()
        for review in queryset:
            review.status = "rejected"
            review.save(update_fields=["status", "updated_at"])
            products.add(review.product)
        for product in products:
            # Rejecting a previously-approved review must drop it back out of the average.
            recompute_product_rating(product)
