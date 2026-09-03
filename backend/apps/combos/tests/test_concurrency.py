"""The combo-group create race, with real threads and real connections.

A savepoint-based simulation cannot express this: the "winner" has to be a row committed
by a DIFFERENT transaction, and anything created inside the test's own transaction rolls
back with the savepoint that catches the IntegrityError. So this is a `TransactionTestCase`
with two threads, the same shape as `apps/inventory/tests/test_concurrency.py`.
"""
import threading
from decimal import Decimal

import pytest
from django.db import connection, connections
from django.test import TransactionTestCase

from apps.carts.models import Cart, CartComboGroup, CartItem
from apps.catalog.factories import ProductVariantFactory
from apps.combos.factories import ComboFactory, ComboItemFactory
from apps.core.models import Country
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.pricing.models import Price


@pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="Real row locking (select_for_update) requires PostgreSQL; SQLite is a no-op.",
)
class AddComboConcurrencyTest(TransactionTestCase):
    # Restore migration-seeded data (countries, currencies) after TransactionTestCase's
    # flush, and don't reset sequences — same reasoning as the inventory test beside it.
    serialized_rollback = True

    def test_two_threads_adding_one_combo_leave_exactly_one_group(self):
        """`add_combo` does `select_for_update()` before deciding whether to create — and
        a SELECT ... FOR UPDATE that matches NO ROW locks nothing. Two concurrent adds of
        the same bundle (a double-tapped Add button is enough) therefore both saw "no
        group" and both created one: the shopper got two identical cards, and the second
        was invisible to the merge for ever after.

        `uniq_cart_combo_group` makes the second insert fail, and `add_combo` folds into
        the winner instead of raising. Both must hold — the constraint alone would turn a
        double-tap into a 500.
        """
        from apps.carts.services import add_combo

        ng = Country.objects.get(code="NG")
        warehouse = WarehouseFactory(location_country="NG", priority=1)
        warehouse.serves_countries.add(ng)

        combo = ComboFactory(discount_percent=Decimal("10"))
        for amount in ("1000.00", "500.00"):
            variant = ProductVariantFactory()
            Price.objects.create(variant=variant, currency=ng.currency, amount=Decimal(amount))
            StockItemFactory(variant=variant, warehouse=warehouse, quantity=100)
            ComboItemFactory(combo=combo, variant=variant, quantity=1)

        cart = Cart.objects.create(user=None, country=ng, currency=ng.currency)

        barrier = threading.Barrier(2)
        errors = []

        def worker():
            barrier.wait()  # both threads reach add_combo at once
            try:
                add_combo(cart, combo, 1, ng)
            except Exception as exc:  # noqa: BLE001 — the point is that NOTHING escapes
                errors.append(f"{type(exc).__name__}: {exc}")
            finally:
                connections.close_all()  # each thread has its own connection

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], errors
        groups = CartComboGroup.objects.filter(cart=cart)
        assert groups.count() == 1, "the double-tap left two identical cards"
        # Both adds landed: one group holding two bundles, not one add silently lost.
        group = groups.get()
        assert group.quantity == 2
        assert sorted(line.quantity for line in group.items.all()) == [2, 2]
        # And no stray lines outside the group.
        assert CartItem.objects.filter(cart=cart, combo_group__isnull=True).count() == 0
