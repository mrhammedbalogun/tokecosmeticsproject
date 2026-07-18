from decimal import Decimal

import pytest

from apps.catalog.factories import ProductFactory


@pytest.mark.django_db
def test_new_product_has_zero_rating():
    p = ProductFactory()
    assert p.rating_avg == Decimal("0.00")
    assert p.rating_count == 0


@pytest.mark.django_db
def test_rating_fields_are_exposed_on_the_list_card(django_user_model, client):
    """A country-resolved product card must carry the denormalised rating so the
    storefront can show stars without a second query."""
    from apps.catalog.factories import PriceFactory

    price = PriceFactory()
    product = price.variant.product
    product.rating_avg = Decimal("4.50")
    product.rating_count = 12
    product.save(update_fields=["rating_avg", "rating_count"])

    r = client.get("/api/v1/products/", HTTP_X_COUNTRY="NG")
    assert r.status_code == 200
    card = next(c for c in r.data["results"] if c["slug"] == product.slug)
    assert card["rating_avg"] == "4.50"
    assert card["rating_count"] == 12
