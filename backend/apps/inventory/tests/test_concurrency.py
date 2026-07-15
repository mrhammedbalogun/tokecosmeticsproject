import threading

import pytest
from django.db import connection, connections
from django.test import TransactionTestCase

from apps.catalog.factories import ProductVariantFactory
from apps.core.models import Country
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.inventory.models import StockMovement
from apps.inventory.services import InsufficientStock, adjust, reconcile, reserve


@pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="Real row locking (select_for_update) requires PostgreSQL; SQLite is a no-op.",
)
class ReserveConcurrencyTest(TransactionTestCase):
    # Restore migration-seeded data (countries, warehouses) after the flush that
    # TransactionTestCase does — and don't reset sequences (that collides with the
    # seeded warehouse ids).
    serialized_rollback = True

    def test_two_threads_last_unit_exactly_one_wins(self):
        ng = Country.objects.get(code="NG")
        w = WarehouseFactory()
        w.serves_countries.add(ng)
        variant = ProductVariantFactory()
        si = StockItemFactory(variant=variant, warehouse=w, quantity=0, reserved=0)
        adjust(si, new_quantity=1, reason="restock", note="seed", user=None)  # exactly 1 unit

        barrier = threading.Barrier(2)
        results = []

        def worker(ref):
            barrier.wait()  # both threads hit reserve() at once
            try:
                reserve(variant, 1, ng, reference=ref)
                results.append("ok")
            except InsufficientStock:
                results.append("fail")
            finally:
                connections.close_all()  # each thread has its own connection

        threads = [threading.Thread(target=worker, args=(f"R{i}",)) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sorted(results) == ["fail", "ok"]  # exactly one succeeded
        si.refresh_from_db()
        assert si.reserved == 1  # never oversold
        assert StockMovement.objects.filter(reason="reservation").count() == 1
        assert reconcile(si)
