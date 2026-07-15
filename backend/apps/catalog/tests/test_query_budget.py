from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.catalog.factories import PriceFactory, ProductFactory, ProductVariantFactory


@pytest.mark.django_db
def test_product_list_query_budget(django_assert_max_num_queries):
    # conftest clears the cache before each test, so this measures the DB path.
    for _ in range(24):
        p = ProductFactory()
        PriceFactory(variant=ProductVariantFactory(product=p), amount=Decimal("1000"))

    c = APIClient()
    with django_assert_max_num_queries(12):
        r = c.get("/api/v1/products/")
    assert r.data["count"] == 24
