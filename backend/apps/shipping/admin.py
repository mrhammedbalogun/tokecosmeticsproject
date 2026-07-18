from django.contrib import admin

from apps.shipping.models import ShippingQuote


@admin.register(ShippingQuote)
class ShippingQuoteAdmin(admin.ModelAdmin):
    list_display = ("order", "status", "amount", "currency", "quoted_at")
    list_filter = ("status",)
    search_fields = ("order__number",)
    readonly_fields = ("note",)
