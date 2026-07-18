from django.contrib import admin

from apps.accounts.models import Address, User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("email", "toke_id", "is_active", "deletion_requested_at",
                    "email_verified_at", "date_joined")
    list_filter = ("is_active", "is_staff", "marketing_consent")
    search_fields = ("email", "toke_id")
    # Never hand-edit identity/audit columns from the admin.
    readonly_fields = ("toke_id", "date_joined", "last_login", "password",
                       "legacy_source", "legacy_wp_id", "legacy_wp_id_intl")


@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = ("user", "label", "country_code", "is_default_shipping")
    list_filter = ("country_code", "is_default_shipping")
    search_fields = ("user__email", "line1", "postcode")
