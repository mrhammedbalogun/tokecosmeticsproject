"""Deleting a variant: `products.manage`, like the rest of the variant surface.

A variant delete CASCADES its price rows, stock rows (and their movements), cart lines
and wishlist entries — order history alone survives via SET_NULL and its name/sku
snapshots. It shipped Owner-only in v0.44.0, and Hammed widened it to Managers the
same day (2026-08-20): a Manager runs the catalogue day-to-day, and the guards that
actually prevent damage — the last-variant refusal and the default promotion — are
role-independent and stay. Deleting the whole PRODUCT remains the Owner elevation.
"""
import pytest
from rest_framework.test import APIClient

from apps.catalog.models import ProductVariant
from apps.catalog.tests.factories_admin import staff_user

pytestmark = pytest.mark.django_db


def _owner_client():
    c = APIClient()
    c.force_authenticate(user=staff_user())
    return c


@pytest.mark.django_db
def test_manager_can_delete_a_variant_but_not_the_product():
    """The line Hammed drew on 2026-08-20: a Manager may prune a variant (with the
    same last-variant and default-promotion guards as the Owner), while deleting the
    PRODUCT stays the products.delete elevation proved in test_admin_crud."""
    from apps.catalog.factories import ProductFactory, ProductVariantFactory

    p = ProductFactory(slug="keeper")
    v = ProductVariantFactory(product=p, sku="KEEP-1", is_default=False)
    ProductVariantFactory(product=p, sku="KEEP-2")

    c = APIClient()
    c.force_authenticate(user=staff_user(email="manager@toke.test", role="Manager"))
    r = c.delete(f"/api/v1/admin/variants/{v.id}/")

    assert r.status_code == 204
    assert not ProductVariant.objects.filter(id=v.id).exists()

    # The product elevation is untouched: the same Manager still cannot delete keeper.
    r = c.delete("/api/v1/admin/products/keeper/")
    assert r.status_code == 403


@pytest.mark.django_db
def test_owner_deletes_a_variant_and_its_dependents_go_with_it():
    from apps.catalog.factories import PriceFactory, ProductFactory, ProductVariantFactory
    from apps.inventory.factories import StockItemFactory
    from apps.inventory.models import StockItem
    from apps.pricing.models import Price

    p = ProductFactory(slug="serum")
    keep = ProductVariantFactory(product=p, sku="SERUM-30", is_default=True)
    doomed = ProductVariantFactory(product=p, sku="SERUM-50", is_default=False)
    PriceFactory(variant=keep)
    PriceFactory(variant=doomed)
    StockItemFactory(variant=doomed)

    r = _owner_client().delete(f"/api/v1/admin/variants/{doomed.id}/")

    assert r.status_code == 204
    assert not ProductVariant.objects.filter(id=doomed.id).exists()
    assert not Price.objects.filter(variant_id=doomed.id).exists()
    assert not StockItem.objects.filter(variant_id=doomed.id).exists()
    # The sibling and its price are untouched.
    assert Price.objects.filter(variant_id=keep.id).exists()


@pytest.mark.django_db
def test_deleting_the_default_variant_promotes_the_next_one():
    """`api_serializers.py:101` falls back to the first variant when none is default,
    but the storefront should never have to rely on the fallback — the delete promotes
    the first remaining variant (position order) in the same transaction."""
    from apps.catalog.factories import ProductFactory, ProductVariantFactory

    p = ProductFactory(slug="butter")
    default = ProductVariantFactory(product=p, sku="BUT-1", is_default=True, position=0)
    # Explicit `is_default=False`: the factory's default is True, which would make the
    # promotion assertion pass without the code under test doing anything.
    second = ProductVariantFactory(product=p, sku="BUT-2", is_default=False, position=1)
    third = ProductVariantFactory(product=p, sku="BUT-3", is_default=False, position=2)

    r = _owner_client().delete(f"/api/v1/admin/variants/{default.id}/")

    assert r.status_code == 204
    second.refresh_from_db()
    third.refresh_from_db()
    assert second.is_default is True
    assert third.is_default is False


@pytest.mark.django_db
def test_the_last_variant_cannot_be_deleted():
    """A product with zero variants is unsellable and invisible in every market — if the
    whole product should go, that is the product delete's job (which this refusal names)."""
    from apps.catalog.factories import ProductFactory, ProductVariantFactory

    p = ProductFactory(slug="solo")
    only = ProductVariantFactory(product=p, sku="SOLO-1", is_default=True)

    r = _owner_client().delete(f"/api/v1/admin/variants/{only.id}/")

    assert r.status_code == 400
    assert "last variant" in str(r.data).lower()
    assert ProductVariant.objects.filter(id=only.id).exists()
