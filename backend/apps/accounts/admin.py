from django.contrib import admin

from apps.accounts.models import Address, LegacyIdentity, User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("email", "toke_id", "is_active", "deletion_requested_at",
                    "email_verified_at", "date_joined")
    list_filter = ("is_active", "is_staff", "marketing_consent")
    search_fields = ("email", "toke_id")
    # Never hand-edit identity/audit columns from the admin.
    readonly_fields = ("toke_id", "date_joined", "last_login", "password", "legacy_source")


@admin.register(LegacyIdentity)
class LegacyIdentityAdmin(admin.ModelAdmin):
    """Read-only. These rows are the idempotency key for the Plan-27 cutover delta run and
    the link Plan-23 attaches orders with — hand-editing one would silently duplicate a
    customer on the next run, or move somebody else's order history onto this account."""

    list_display = ("store", "wp_user_id", "user")
    list_filter = ("store",)
    search_fields = ("user__email", "user__toke_id", "wp_user_id")
    readonly_fields = ("user", "store", "wp_user_id")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = ("user", "label", "country_code", "is_default_shipping")
    list_filter = ("country_code", "is_default_shipping")
    search_fields = ("user__email", "line1", "postcode")
