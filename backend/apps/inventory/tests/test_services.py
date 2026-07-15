import pytest

from apps.catalog.factories import ProductVariantFactory
from apps.core.models import Country
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.inventory.models import StockItem, StockMovement
from apps.inventory.services import (
    InsufficientStock,
    available_for_country,
    commit_sale,
    release,
    reserve,
)


@pytest.fixture
def ng(db):
    return Country.objects.get(code="NG")


def _wh(country, **kw):
    w = WarehouseFactory(**kw)
    w.serves_countries.add(country)
    return w


@pytest.mark.django_db
def test_available_for_country_sums_serving_warehouses(ng):
    v = ProductVariantFactory()
    StockItemFactory(variant=v, warehouse=_wh(ng), quantity=10, reserved=2)
    StockItemFactory(variant=v, warehouse=_wh(ng), quantity=5, reserved=0)
    assert available_for_country(v, ng) == 13


@pytest.mark.django_db
def test_reserve_then_release_roundtrip(ng):
    v = ProductVariantFactory()
    si = StockItemFactory(variant=v, warehouse=_wh(ng), quantity=10)
    reserve(v, 4, ng, reference="ORD-1")
    si.refresh_from_db()
    assert si.reserved == 4
    assert available_for_country(v, ng) == 6

    release("ORD-1")
    si.refresh_from_db()
    assert si.reserved == 0
    assert available_for_country(v, ng) == 10


@pytest.mark.django_db
def test_reserve_insufficient_raises(ng):
    v = ProductVariantFactory()
    StockItemFactory(variant=v, warehouse=_wh(ng), quantity=2)
    with pytest.raises(InsufficientStock):
        reserve(v, 3, ng, reference="ORD-2")
    assert available_for_country(v, ng) == 2  # nothing reserved on failure


@pytest.mark.django_db
def test_reserve_splits_across_warehouses_by_priority(ng):
    v = ProductVariantFactory()
    StockItemFactory(variant=v, warehouse=_wh(ng, priority=1), quantity=3)
    StockItemFactory(variant=v, warehouse=_wh(ng, priority=2), quantity=5)
    reserve(v, 5, ng, reference="ORD-3")  # 3 from priority-1, 2 from priority-2
    items = {si.warehouse.priority: si for si in StockItem.objects.filter(variant=v)}
    assert items[1].reserved == 3
    assert items[2].reserved == 2


@pytest.mark.django_db
def test_reserve_is_idempotent_per_reference(ng):
    v = ProductVariantFactory()
    si = StockItemFactory(variant=v, warehouse=_wh(ng), quantity=10)
    reserve(v, 2, ng, reference="ORD-4")
    reserve(v, 2, ng, reference="ORD-4")  # replay -> no double reserve
    si.refresh_from_db()
    assert si.reserved == 2


@pytest.mark.django_db
def test_commit_sale_decrements_quantity_and_reserved(ng):
    v = ProductVariantFactory()
    si = StockItemFactory(variant=v, warehouse=_wh(ng), quantity=10)
    reserve(v, 3, ng, reference="ORD-5")
    commit_sale("ORD-5")
    si.refresh_from_db()
    assert si.quantity == 7
    assert si.reserved == 0
    # release after commit is a no-op (ledger already settled).
    release("ORD-5")
    si.refresh_from_db()
    assert si.reserved == 0 and si.quantity == 7


@pytest.mark.django_db
def test_release_is_idempotent(ng):
    v = ProductVariantFactory()
    si = StockItemFactory(variant=v, warehouse=_wh(ng), quantity=10)
    reserve(v, 4, ng, reference="ORD-6")
    release("ORD-6")
    release("ORD-6")  # second call no-op
    si.refresh_from_db()
    assert si.reserved == 0
    assert StockMovement.objects.filter(reference="ORD-6", reason="release").count() == 1
