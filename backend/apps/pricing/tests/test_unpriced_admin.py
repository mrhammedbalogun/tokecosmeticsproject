"""The unpriced-per-market checklist (Plan-17c Task 2).

"A market needs a price in its currency before the product appears there at all" — the
products list already says which currencies a product is missing, but there was no way to
ask the opposite question: *for this market, what is not sellable yet?* That is the list
somebody works through on the day a new country opens, and doing it by eye across 121
prices is how a product quietly stays invisible.

Only ACTIVE products count. A draft or archived product missing a GBP price is not a gap
in the catalogue; it is a product nobody is trying to sell.
"""
import pytest
from rest_framework.test import APIClient

from apps.catalog.factories import ProductVariantFactory
from apps.catalog.tests.factories_admin import staff_user
from apps.core.models import Currency
from apps.pricing.models import Price

pytestmark = pytest.mark.django_db

URL = "/api/v1/admin/prices/unpriced/"


@pytest.fixture
def client():
    c = APIClient()
    c.force_authenticate(user=staff_user())
    return c


def _currency(code="GBP"):
    obj, _ = Currency.objects.get_or_create(
        code=code, defaults={"name": code, "symbol": "£", "decimals": 2}
    )
    return obj


def test_requires_staff():
    assert APIClient().get(f"{URL}?currency=GBP").status_code in (401, 403)


def test_currency_is_required(client):
    """Without one the endpoint would have to invent a market, and the honest answer to
    'unpriced in what?' is a 400."""
    assert client.get(URL).status_code == 400


def test_lists_a_variant_with_no_price_in_that_currency(client):
    _currency("GBP")
    variant = ProductVariantFactory()

    rows = client.get(f"{URL}?currency=GBP").data["results"]

    assert [r["sku"] for r in rows] == [variant.sku]


def test_a_variant_priced_in_that_currency_is_not_listed(client):
    gbp = _currency("GBP")
    variant = ProductVariantFactory()
    Price.objects.create(variant=variant, currency=gbp, amount="10.00")

    rows = client.get(f"{URL}?currency=GBP").data["results"]

    assert rows == []


def test_a_price_in_a_DIFFERENT_currency_does_not_count(client):
    """The bug this endpoint exists to make visible: every one of the 121 production
    prices is NGN, so a naive 'has a price' check would call the whole catalogue ready
    for the UK."""
    _currency("GBP")
    ngn = _currency("NGN")
    variant = ProductVariantFactory()
    Price.objects.create(variant=variant, currency=ngn, amount="18500.00")

    rows = client.get(f"{URL}?currency=GBP").data["results"]

    assert [r["sku"] for r in rows] == [variant.sku]


def test_only_active_products_are_counted_as_gaps(client):
    _currency("GBP")
    live = ProductVariantFactory()
    draft = ProductVariantFactory()
    draft.product.status = "draft"
    draft.product.save(update_fields=["status"])

    rows = client.get(f"{URL}?currency=GBP").data["results"]

    skus = [r["sku"] for r in rows]
    assert live.sku in skus
    assert draft.sku not in skus


def test_a_row_names_the_product_a_human_would_look_for(client):
    _currency("GBP")
    variant = ProductVariantFactory()

    row = client.get(f"{URL}?currency=GBP").data["results"][0]

    assert row["product_name"] == variant.product.name
    assert row["product_slug"] == variant.product.slug
    assert row["variant_id"] == variant.id
