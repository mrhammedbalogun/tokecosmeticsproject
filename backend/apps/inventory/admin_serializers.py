from rest_framework import serializers

from apps.core.models import Country
from apps.inventory.models import StockItem, StockMovement, Warehouse


class WarehouseAdminSerializer(serializers.ModelSerializer):
    """Plan-17c Task 1. CRUD minus delete — see the viewset for why deletion is refused.

    `serves_countries` is the field to be careful with: `inventory/services.reserve()`
    filters candidates on `warehouse__is_active=True, warehouse__serves_countries=country`,
    so it is closer to a kill switch than to a checkbox. Unticking NG on Lagos HQ removes
    the only warehouse serving Nigeria and every checkout in the only sellable market
    fails, silently, until a customer tries to buy something.

    It stays writable — reorganising warehouses is legitimate work, and the backend cannot
    tell a mistake from step one of a two-step move. What it must not do is let the edit
    look ordinary, so `countries_left_unserved` publishes the consequence for the admin to
    name in its confirmation. COMPUTED here rather than asserted in the UI, because the
    answer depends on every OTHER warehouse's coverage and only the server sees them all.
    """

    audit_allowlist = ("name", "location_country", "serves_countries", "priority", "is_active")

    countries_left_unserved = serializers.SerializerMethodField()
    # OPTIONAL ON CREATE, deliberately. A warehouse serving nothing is inert — `reserve()`
    # simply never picks it — so "create the depot, then decide what it serves" is a safe
    # order to work in. Requiring it up front would push the operator to tick a country
    # before the place has any stock, which is the one way a new warehouse can take
    # allocation away from a working one.
    serves_countries = serializers.PrimaryKeyRelatedField(
        many=True, required=False, queryset=Country.objects.all()
    )

    class Meta:
        model = Warehouse
        fields = [
            "id", "name", "location_country", "serves_countries",
            "priority", "is_active", "countries_left_unserved",
        ]

    def get_countries_left_unserved(self, warehouse) -> list[str]:
        """Countries this warehouse serves that NO other active warehouse does — i.e. the
        markets that lose their last supply line if this one is deactivated or stops
        serving them. `is_active=False` is not cover, because `reserve()` skips it."""
        if warehouse.pk is None:
            return []
        covered_elsewhere = set(
            Warehouse.objects.filter(is_active=True)
            .exclude(pk=warehouse.pk)
            .values_list("serves_countries__code", flat=True)
        )
        return sorted(
            code
            for code in warehouse.serves_countries.values_list("code", flat=True)
            if code not in covered_elsewhere
        )


class StockItemSerializer(serializers.ModelSerializer):
    # `quantity` and `reserved` are read-only here (they move only through adjust/
    # reserve), so an audit row for a stock CREATE records what was pointed at and
    # the threshold -- never a number this endpoint could not have written.
    audit_allowlist = ("variant", "warehouse", "low_stock_threshold")

    available = serializers.IntegerField(read_only=True)
    sku = serializers.CharField(source="variant.sku", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)

    class Meta:
        model = StockItem
        fields = [
            "id", "variant", "sku", "warehouse", "warehouse_name",
            "quantity", "reserved", "available", "low_stock_threshold",
        ]
        read_only_fields = ["quantity", "reserved"]  # numbers change only via adjust/reserve


class StockAdjustSerializer(serializers.Serializer):
    # THE consequential inventory write: it sets the number that decides whether an
    # order can be placed at all. All three keys are recorded, `note` included --
    # a stock write-off with no stated reason is exactly the row somebody will want
    # to read back.
    audit_allowlist = ("quantity", "reason", "note")

    quantity = serializers.IntegerField(min_value=0)
    # "migration" is excluded: it's a machine-only sentinel the Plan-21
    # import_catalog importer relies on to detect stock nobody has touched
    # since the last migration run (apps/migration_wp/importers/stock.py). A
    # human must never be able to write it via this endpoint -- doing so
    # would silently strip that item's clobber-guard protection, exposing it
    # to being overwritten by the next migration re-run.
    reason = serializers.ChoiceField(
        choices=[c[0] for c in StockMovement.REASONS if c[0] != "migration"]
    )
    note = serializers.CharField()  # required — no silent stock changes


class StockMovementSerializer(serializers.ModelSerializer):
    sku = serializers.CharField(source="stock_item.variant.sku", read_only=True)

    class Meta:
        model = StockMovement
        fields = [
            "id", "stock_item", "sku", "delta_quantity", "delta_reserved",
            "reason", "reference", "note", "created_by", "created_at",
        ]
