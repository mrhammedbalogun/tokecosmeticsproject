from django.contrib import admin

from apps.stores.models import StoreLocation


@admin.register(StoreLocation)
class StoreLocationAdmin(admin.ModelAdmin):
    list_display = ("name", "store_type", "country", "state_region", "area_region", "status")
    list_filter = ("store_type", "country", "is_active")
    search_fields = ("name", "address", "phone", "city_text")
    autocomplete_fields = ()
    readonly_fields = ("name_key", "address_key", "created_at", "updated_at")
