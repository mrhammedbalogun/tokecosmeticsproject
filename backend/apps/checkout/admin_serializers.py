"""Coupon administration (Plan-19b). `marketing.manage`.

The model and its redemption ledger have existed since Plan-08c; production holds zero of
both. Nothing could create one without a database client, which is why the launch
marketing lever has never been pulled.
"""
from rest_framework import serializers

from apps.checkout.models import Coupon


class CouponAdminSerializer(serializers.ModelSerializer):
    """A coupon is money off, so every field that decides how much is on the audit
    allow-list. `code` is stored upper-case and uniqueness is case-insensitive at the
    database (`uniq_coupon_code_ci`), so it is normalised here rather than letting two
    people create `SUMMER` and `summer` and discover the collision at checkout.
    """

    audit_allowlist = (
        "code", "type", "value", "currency", "min_subtotal", "starts_at", "ends_at",
        "usage_limit", "usage_limit_per_user", "is_active",
        "applies_to_products", "applies_to_categories",
    )

    # Read-only usage, so a manager can see whether a code is working without opening a
    # report. Annotated by the viewset; `0` when the annotation is absent.
    redemption_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Coupon
        fields = [
            "id", "code", "type", "value", "currency", "min_subtotal",
            "starts_at", "ends_at", "usage_limit", "usage_limit_per_user",
            "applies_to_products", "applies_to_categories", "is_active",
            "redemption_count", "created_at",
        ]

    def validate_code(self, value: str) -> str:
        return value.strip().upper()

    def validate(self, attrs):
        """The one combination that silently does nothing: a fixed-amount coupon with no
        currency. `resolve` cannot compare it to a cart total, so it would never apply and
        nobody would know why."""
        coupon_type = attrs.get("type", getattr(self.instance, "type", None))
        currency = attrs.get("currency", getattr(self.instance, "currency", None))
        if coupon_type == "fixed" and currency is None:
            raise serializers.ValidationError(
                {"currency": "A fixed-amount coupon needs a currency."}
            )
        return attrs
