from django.contrib import admin

from apps.delivery.models import DeliveryOption, DeliveryOptionRate


class DeliveryOptionRateInline(admin.TabularInline):
    model = DeliveryOptionRate
    extra = 1


@admin.register(DeliveryOption)
class DeliveryOptionAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "kind",
        "currency",
        "price",
        "free_over",
        "quote_required",
        "disclaimer",
        "is_active",
        "sort",
    )
    list_filter = ("is_active", "quote_required", "kind", "currency")
    search_fields = ("name",)
    filter_horizontal = ("countries", "regions")
    inlines = [DeliveryOptionRateInline]
