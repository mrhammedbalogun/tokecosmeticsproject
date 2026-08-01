"""Delivery option administration (Plan-19b).

FLAT FIELDS ONLY. Coverage (`countries`, `regions`) is read-only here and gets its own
screen in 19d, because editing it means choosing among 811 regions in a tree — a different
problem from "the Lagos price went up", which is the edit an operator actually makes month
to month as fuel and logistics costs move.

Weight tiers (`DeliveryOptionRate`) are deliberately absent: production has zero rows, and
a tier editor for an unpopulated table would be speculative UI.
"""
from rest_framework import serializers

from apps.delivery.models import DeliveryOption


class DeliveryOptionAdminSerializer(serializers.ModelSerializer):
    audit_allowlist = (
        "name", "kind", "carrier_code", "price", "currency", "free_over",
        "quote_required", "disclaimer", "min_days", "max_days", "is_active", "sort",
    )

    country_codes = serializers.SlugRelatedField(
        source="countries", slug_field="code", many=True, read_only=True
    )
    region_count = serializers.IntegerField(source="regions.count", read_only=True)
    # The ids the coverage picker starts from. Read-only here — writing coverage goes
    # through the `coverage` action, for the reason `DeliveryCoverageSerializer` gives.
    region_ids = serializers.PrimaryKeyRelatedField(
        source="regions", many=True, read_only=True
    )

    class Meta:
        model = DeliveryOption
        fields = [
            "id", "name", "kind", "carrier_code", "price", "currency", "free_over",
            "quote_required", "disclaimer", "min_days", "max_days", "is_active", "sort",
            "country_codes", "region_count", "region_ids",
        ]

    def validate(self, attrs):
        """`min_days` above `max_days` renders as "3-1 days" on the storefront and reads
        as a bug in the shop rather than a typo in the admin."""
        minimum = attrs.get("min_days", getattr(self.instance, "min_days", None))
        maximum = attrs.get("max_days", getattr(self.instance, "max_days", None))
        if minimum is not None and maximum is not None and minimum > maximum:
            raise serializers.ValidationError(
                {"min_days": "The fastest estimate cannot be slower than the slowest."}
            )
        return attrs


class RegionAdminSerializer(serializers.ModelSerializer):
    """A state or an area, flat. The TREE is assembled by the client from `parent` —
    811 rows for Nigeria is one small response, and shipping it whole beats 37 requests
    to expand each state."""

    audit_allowlist = ("name", "is_active")

    class Meta:
        from apps.core.models import Region

        model = Region
        fields = ["id", "country_code", "name", "level", "parent", "is_active"]


class DeliveryCoverageSerializer(serializers.Serializer):
    """The coverage write, kept apart from the flat-field serializer on purpose.

    Coverage is MIXED GRANULARITY (master spec Decision 13): an option can serve whole
    countries, whole states, or individual areas, in any combination. Putting that on the
    same PATCH as `price` would mean an operator editing a price could silently clear
    every region if their client omitted the key — the exact class of accident that makes
    "why did Lagos stop being served?" unanswerable.
    """

    country_codes = serializers.ListField(child=serializers.CharField(), required=False)
    region_ids = serializers.ListField(child=serializers.IntegerField(), required=False)
