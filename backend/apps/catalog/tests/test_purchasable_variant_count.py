"""`purchasable_variant_count` on the product card.

The storefront card reads it to choose between "Add to Cart" (one option — nothing to
choose) and "Choose Option" (several — send the shopper to the PDP). It therefore has to
count what the PDP would let them pick in THIS country, not how many variant rows exist.
"""
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.catalog.factories import PriceFactory, ProductFactory, ProductVariantFactory
from apps.core.models import Country
from apps.inventory.factories import StockItemFactory, WarehouseFactory


@pytest.fixture
def ng_warehouse(db):
    ng = Country.objects.get(code="NG")
    wh = WarehouseFactory()
    wh.serves_countries.add(ng)
    return ng, wh


def card_for(slug, country="NG"):
    res = APIClient().get("/api/v1/products/", HTTP_X_COUNTRY=country)
    assert res.status_code == 200
    return next(r for r in res.data["results"] if r["slug"] == slug)


@pytest.mark.django_db
class TestPurchasableVariantCount:
    def test_counts_one_for_a_single_variant_product(self, ng_warehouse):
        _, wh = ng_warehouse
        product = ProductFactory()
        v = ProductVariantFactory(product=product, is_default=True)
        PriceFactory(variant=v, amount=Decimal("1000"))
        StockItemFactory(variant=v, warehouse=wh, quantity=5)
        assert card_for(product.slug)["purchasable_variant_count"] == 1

    def test_counts_every_priced_variant(self, ng_warehouse):
        _, wh = ng_warehouse
        product = ProductFactory()
        for i in range(3):
            v = ProductVariantFactory(product=product, is_default=(i == 0), position=i)
            PriceFactory(variant=v, amount=Decimal("1000") + i)
            StockItemFactory(variant=v, warehouse=wh, quantity=5)
        assert card_for(product.slug)["purchasable_variant_count"] == 3

    def test_ignores_inactive_variants(self, ng_warehouse):
        _, wh = ng_warehouse
        product = ProductFactory()
        live = ProductVariantFactory(product=product, is_default=True, position=0)
        dead = ProductVariantFactory(product=product, position=1, is_active=False)
        for v in (live, dead):
            PriceFactory(variant=v, amount=Decimal("1000"))
        StockItemFactory(variant=live, warehouse=wh, quantity=5)
        assert card_for(product.slug)["purchasable_variant_count"] == 1

    def test_ignores_variants_with_no_price_in_this_country(self, ng_warehouse):
        """The card must not send a shopper to pick between one real option and a
        variant the PDP will show as "Unavailable"."""
        _, wh = ng_warehouse
        product = ProductFactory()
        priced = ProductVariantFactory(product=product, is_default=True, position=0)
        unpriced = ProductVariantFactory(product=product, position=1)
        PriceFactory(variant=priced, amount=Decimal("1000"))
        StockItemFactory(variant=priced, warehouse=wh, quantity=5)
        StockItemFactory(variant=unpriced, warehouse=wh, quantity=5)
        assert card_for(product.slug)["purchasable_variant_count"] == 1

    def test_counts_a_variant_whose_sale_window_has_closed(self, ng_warehouse):
        """resolve_price falls back to a windowless price and, failing that, to a
        closed-window one — so a lapsed sale price still leaves the variant an option.
        A window filter in the count would undercount exactly these."""
        _, wh = ng_warehouse
        past = timezone.now() - timezone.timedelta(days=30)
        product = ProductFactory()
        plain = ProductVariantFactory(product=product, is_default=True, position=0)
        lapsed = ProductVariantFactory(product=product, position=1)
        PriceFactory(variant=plain, amount=Decimal("1000"))
        PriceFactory(
            variant=lapsed, amount=Decimal("900"),
            starts_at=past, ends_at=past + timezone.timedelta(days=1),
        )
        for v in (plain, lapsed):
            StockItemFactory(variant=v, warehouse=wh, quantity=5)
        assert card_for(product.slug)["purchasable_variant_count"] == 2

    def test_multiple_prices_on_one_variant_count_once(self, ng_warehouse):
        """A variant priced both globally and for NG is still ONE option."""
        ng, wh = ng_warehouse
        product = ProductFactory()
        v = ProductVariantFactory(product=product, is_default=True)
        PriceFactory(variant=v, amount=Decimal("1000"))                 # country=None
        PriceFactory(variant=v, amount=Decimal("950"), country=ng)
        StockItemFactory(variant=v, warehouse=wh, quantity=5)
        assert card_for(product.slug)["purchasable_variant_count"] == 1

    def test_search_results_carry_the_count(self, ng_warehouse):
        _, wh = ng_warehouse
        product = ProductFactory(name="Shea Butter Deluxe")
        for i in range(2):
            v = ProductVariantFactory(product=product, is_default=(i == 0), position=i)
            PriceFactory(variant=v, amount=Decimal("1000"))
            StockItemFactory(variant=v, warehouse=wh, quantity=5)
        res = APIClient().get("/api/v1/search/?q=Shea", HTTP_X_COUNTRY="NG")
        assert res.status_code == 200
        row = next(r for r in res.data["results"] if r["slug"] == product.slug)
        assert row["purchasable_variant_count"] == 2

    def test_related_products_on_the_pdp_carry_the_count(self, ng_warehouse):
        """The PDP's "You may also like" strip is the same card, and a card there that
        says Add to Cart would add whichever variant the API listed first."""
        _, wh = ng_warehouse
        main = ProductFactory()
        v_main = ProductVariantFactory(product=main, is_default=True)
        PriceFactory(variant=v_main, amount=Decimal("1000"))
        StockItemFactory(variant=v_main, warehouse=wh, quantity=5)

        friend = ProductFactory()
        for i in range(2):
            v = ProductVariantFactory(product=friend, is_default=(i == 0), position=i)
            PriceFactory(variant=v, amount=Decimal("1000") + i)
            StockItemFactory(variant=v, warehouse=wh, quantity=5)
        main.related.add(friend)

        res = APIClient().get(f"/api/v1/products/{main.slug}/", HTTP_X_COUNTRY="NG")
        assert res.status_code == 200
        row = next(r for r in res.data["related"] if r["slug"] == friend.slug)
        assert row["purchasable_variant_count"] == 2

    def test_wishlist_card_counts_without_the_annotation(self, ng_warehouse, django_user_model):
        """The wishlist serializes a lone Product with no annotation — the fallback
        path must agree with the annotated one."""
        _, wh = ng_warehouse
        from apps.wishlist.models import WishlistItem

        product = ProductFactory()
        variants = []
        for i in range(2):
            v = ProductVariantFactory(product=product, is_default=(i == 0), position=i)
            PriceFactory(variant=v, amount=Decimal("1000"))
            StockItemFactory(variant=v, warehouse=wh, quantity=5)
            variants.append(v)
        user = django_user_model.objects.create_user(
            email="wish@example.com", password="pw12345!x")
        WishlistItem.objects.create(user=user, variant=variants[0])
        client = APIClient()
        client.force_authenticate(user=user)
        res = client.get("/api/v1/me/wishlist/", HTTP_X_COUNTRY="NG")
        assert res.status_code == 200
        assert res.data[0]["product"]["purchasable_variant_count"] == 2
