from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.catalog.factories import PriceFactory, ProductFactory, ProductVariantFactory


@pytest.mark.django_db
def test_list_cache_invalidates_on_new_product(settings):
    settings.CACHES = {
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "t"}
    }
    from django.core.cache import cache

    cache.clear()
    p = ProductFactory()
    PriceFactory(variant=ProductVariantFactory(product=p), amount=Decimal("1000"))

    c = APIClient()
    assert c.get("/api/v1/products/").data["count"] == 1
    # Add another priced product -> the post_save signal must bust the cached list.
    p2 = ProductFactory()
    PriceFactory(variant=ProductVariantFactory(product=p2), amount=Decimal("2000"))
    assert c.get("/api/v1/products/").data["count"] == 2
