import pytest
from django.core.management import call_command

from apps.catalog.models import ProductVariant
from apps.inventory.models import StockItem, StockMovement, Warehouse
from apps.inventory.services import reconcile

pytestmark = pytest.mark.django_db

PLACEHOLDER = 100


@pytest.fixture
def lagos(db):
    return Warehouse.objects.get_or_create(
        name="Lagos HQ", defaults={"location_country": "NG"}
    )[0]


def test_instock_seeds_placeholder_and_outofstock_seeds_zero(artifact_path, lagos):
    call_command("import_catalog", str(artifact_path), "--skip-media")
    assert StockItem.objects.get(variant__sku="TC-WP-101", warehouse=lagos).quantity == PLACEHOLDER
    assert StockItem.objects.get(variant__sku="TC-WP-105", warehouse=lagos).quantity == 0


def test_stock_movement_recorded_for_audit(artifact_path, lagos):
    call_command("import_catalog", str(artifact_path), "--skip-media")
    item = StockItem.objects.get(variant__sku="TC-WP-101", warehouse=lagos)
    assert item.movements.filter(reason="migration").exists()


def test_uk_warehouse_is_not_seeded(artifact_path, lagos):
    """The intl store has no SKUs and no stock quantities to seed from."""
    call_command("import_catalog", str(artifact_path), "--skip-media")
    uk = Warehouse.objects.filter(name="UK Warehouse").first()
    if uk is not None:
        assert StockItem.objects.filter(warehouse=uk).count() == 0


def test_rerun_does_not_duplicate_stock_items(artifact_path, lagos):
    call_command("import_catalog", str(artifact_path), "--skip-media")
    call_command("import_catalog", str(artifact_path), "--skip-media")
    assert StockItem.objects.filter(variant__sku="TC-WP-101").count() == 1


def test_rerun_does_not_clobber_hand_edited_stock(artifact_path, lagos, capsys):
    """THE CLOBBER TRAP. Hammed's team enters real counts before launch; the
    Plan-27 cutover re-run must not reset them to the placeholder."""
    call_command("import_catalog", str(artifact_path), "--skip-media")

    item = StockItem.objects.get(variant__sku="TC-WP-101", warehouse=lagos)
    item.quantity = 7
    item.save(update_fields=["quantity"])
    StockMovement.objects.create(stock_item=item, delta_quantity=-93, reason="adjustment")

    call_command("import_catalog", str(artifact_path), "--skip-media")

    item.refresh_from_db()
    assert item.quantity == 7, "migration overwrote a hand-entered stock count"
    assert "protected" in capsys.readouterr().out


def test_force_stock_overrides_the_guard(artifact_path, lagos):
    call_command("import_catalog", str(artifact_path), "--skip-media")
    item = StockItem.objects.get(variant__sku="TC-WP-101", warehouse=lagos)
    item.quantity = 7
    item.save(update_fields=["quantity"])
    StockMovement.objects.create(stock_item=item, delta_quantity=-93, reason="adjustment")

    call_command("import_catalog", str(artifact_path), "--skip-media", "--force-stock")

    item.refresh_from_db()
    assert item.quantity == PLACEHOLDER


def test_skip_stock_creates_no_stock_at_all(artifact_path, lagos):
    call_command("import_catalog", str(artifact_path), "--skip-media", "--skip-stock")
    assert StockItem.objects.count() == 0


def test_every_variant_gets_a_stock_item(artifact_path, lagos):
    call_command("import_catalog", str(artifact_path), "--skip-media")
    assert StockItem.objects.count() == ProductVariant.objects.count()


def test_reconcile_holds_after_two_runs(artifact_path, lagos):
    """Regression guard for the delta_quantity bug: writing the absolute
    quantity as the movement's delta corrupts the ledger the moment an item
    is re-touched by a second run. This importer runs at least three times
    (rehearsal, then cutover), so every re-touched item would end up with a
    ledger that no longer sums to its live quantity."""
    call_command("import_catalog", str(artifact_path), "--skip-media")
    call_command("import_catalog", str(artifact_path), "--skip-media")

    item = StockItem.objects.get(variant__sku="TC-WP-101", warehouse=lagos)
    assert reconcile(item) is True


def test_force_stock_reprotects_on_next_ordinary_run(artifact_path, lagos):
    """Using --force-stock once must not leave the item permanently exposed.
    A forced overwrite is recorded as reason="adjustment", not "migration",
    so the very next ordinary run (no flags at all) treats the item as
    hand-edited again and protects it -- the guard re-arms itself."""
    import io

    call_command("import_catalog", str(artifact_path), "--skip-media")

    item = StockItem.objects.get(variant__sku="TC-WP-101", warehouse=lagos)
    item.quantity = 7
    item.save(update_fields=["quantity"])
    StockMovement.objects.create(stock_item=item, delta_quantity=-93, reason="adjustment")

    call_command("import_catalog", str(artifact_path), "--skip-media", "--force-stock")
    item.refresh_from_db()
    assert item.quantity == PLACEHOLDER, "force-stock did not overwrite the hand-edited item"

    out = io.StringIO()
    call_command("import_catalog", str(artifact_path), "--skip-media", stdout=out)
    item.refresh_from_db()
    assert item.quantity == PLACEHOLDER, "an ordinary run after --force-stock clobbered the item"
    assert "protected" in out.getvalue()
