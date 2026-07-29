from rest_framework import serializers

from apps.inventory.models import StockItem, StockMovement


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
