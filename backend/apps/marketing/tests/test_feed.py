"""The product feed the four ad platforms fetch.

The assertion this file exists for is the FIRST one: the feed's `<g:id>` and the
conversion event's `content_id` must be the same string. Nothing else in the system
notices when they are not — the feed imports cleanly, the pixel fires cleanly, and
dynamic retargeting just shows nobody anything.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from django.test import Client

from apps.catalog.factories import BrandFactory, PriceFactory, ProductFactory, ProductVariantFactory
from apps.core.models import Country
from apps.inventory.models import StockItem, Warehouse
from apps.marketing.feed import build_feed

pytestmark = pytest.mark.django_db


def ng() -> Country:
    return Country.objects.get(code="NG")


def gb() -> Country:
    return Country.objects.get(code="GB")


def priced_product(*, sku="TOKE-SER-50", amount="12000.00", country=None, **kwargs):
    product = ProductFactory(status="active", **kwargs)
    variant = ProductVariantFactory(product=product, sku=sku)
    PriceFactory(variant=variant, amount=Decimal(amount), country=country)
    return product, variant


def test_the_feed_id_is_the_sku_the_conversion_event_also_sends():
    """**The contract the whole retargeting half of Plan-44 rests on.**

    `apps/marketing/events._contents` sends `OrderItem.sku` and the browser pixel puts
    the same string in `content_ids`. If this ever stops matching, a visitor who viewed
    `TOKE-SER-50` gets retargeted with a product id the platform has never heard of, and
    shows them nothing. No error is raised anywhere in that chain.
    """
    priced_product(sku="TOKE-SER-50")

    xml = build_feed(ng())

    assert "<g:id>TOKE-SER-50</g:id>" in xml


def test_price_carries_its_currency_because_a_bare_number_is_rejected():
    priced_product(amount="12000.00")
    assert "<g:price>12000.00 NGN</g:price>" in build_feed(ng())


def test_a_sale_price_puts_the_was_price_in_g_price_and_the_now_price_in_sale_price():
    """That way round, which is the opposite of how it reads. Backwards, the feed
    advertises the higher number as the offer."""
    product = ProductFactory(status="active")
    variant = ProductVariantFactory(product=product, sku="SALE-1")
    PriceFactory(variant=variant, amount=Decimal("8000.00"),
                 compare_at_amount=Decimal("12000.00"))

    xml = build_feed(ng())

    assert "<g:price>12000.00 NGN</g:price>" in xml
    assert "<g:sale_price>8000.00 NGN</g:sale_price>" in xml


def test_variants_of_one_product_share_an_item_group_id():
    """So a platform shows ONE product with sizes, not eight near-identical listings."""
    product = ProductFactory(status="active", slug="radiance-serum")
    for sku in ("RS-30", "RS-50"):
        variant = ProductVariantFactory(product=product, sku=sku)
        PriceFactory(variant=variant, amount=Decimal("9000.00"))

    xml = build_feed(ng())

    assert xml.count("<g:item_group_id>radiance-serum</g:item_group_id>") == 2


def test_a_draft_product_is_never_advertised():
    """`Product.STATUS` is draft/active/archived — there is no "published". A filter on
    a status no product holds produces an EMPTY feed that every platform accepts
    silently, which is why this test names the vocabulary explicitly."""
    ProductFactory(status="draft")
    priced_product(sku="LIVE-1")

    xml = build_feed(ng())

    assert "<g:id>LIVE-1</g:id>" in xml
    assert xml.count("<item>") == 1


def test_an_unpriced_variant_is_left_out_rather_than_advertised_at_nothing():
    """Same "hide until priced" rule the storefront applies."""
    product = ProductFactory(status="active")
    ProductVariantFactory(product=product, sku="NO-PRICE")

    assert "<item>" not in build_feed(ng())


def test_a_market_restricted_product_is_not_advertised_into_another_market():
    product, _ = priced_product(sku="NG-ONLY")
    product.available_countries.set([ng()])

    assert "<g:id>NG-ONLY</g:id>" in build_feed(ng())
    assert "<g:id>NG-ONLY</g:id>" not in build_feed(gb())


def test_availability_follows_the_warehouses_that_serve_the_market():
    """A feed advertising Nigerian stock to a British shopper buys clicks that cannot
    convert — the expensive kind of wrong."""
    _, variant = priced_product(sku="STOCKED")
    warehouse = Warehouse.objects.create(name="Lagos HQ", is_active=True)
    warehouse.serves_countries.set([ng()])
    StockItem.objects.create(variant=variant, warehouse=warehouse, quantity=10, reserved=0)

    assert "<g:availability>in stock</g:availability>" in build_feed(ng())


def test_a_variant_with_no_stock_anywhere_is_listed_as_out_of_stock_not_dropped():
    """Still in the feed: a platform that loses the item loses its history and its
    performance data, and the product comes back into stock."""
    priced_product(sku="SOLD-OUT")
    assert "<g:availability>out of stock</g:availability>" in build_feed(ng())


def test_the_brand_falls_back_to_the_shops_own_name():
    priced_product(sku="NO-BRAND")
    assert "<g:brand>Toke Cosmetics</g:brand>" in build_feed(ng())

    product, variant = priced_product(sku="BRANDED")
    product.brand = BrandFactory(name="Toke Pro")
    product.save(update_fields=["brand"])
    assert "<g:brand>Toke Pro</g:brand>" in build_feed(ng())


def test_titles_and_descriptions_are_xml_escaped():
    """A product name with an ampersand in it is not exotic, and an unescaped one makes
    the whole document unparseable — every item in it disappears at once."""
    import xml.etree.ElementTree as ET

    priced_product(sku="AMP-1", name="Shea & Honey <Butter>")

    xml = build_feed(ng())

    assert "&amp;" in xml
    ET.fromstring(xml)  # raises if the document is malformed


def test_the_endpoint_serves_xml_and_names_an_unknown_market():
    priced_product(sku="ENDPOINT-1")
    client = Client()

    ok = client.get("/api/v1/marketing/feed/products.xml?country=NG")
    assert ok.status_code == 200
    assert ok["Content-Type"].startswith("application/xml")
    assert b"ENDPOINT-1" in ok.content

    # A market that does not exist is a mistake in somebody's ad account; saying so is
    # more useful than silently serving Nigeria's catalogue to a Kenyan ad set.
    assert client.get("/api/v1/marketing/feed/products.xml?country=KE").status_code == 404


def test_the_endpoint_defaults_to_nigeria_and_needs_no_credential():
    """Public on purpose: every platform fetches a feed URL on its own schedule from its
    own infrastructure and supports nothing more than a URL. What it publishes is the
    catalogue, which is already on the storefront."""
    priced_product(sku="DEFAULT-1")

    response = Client().get("/api/v1/marketing/feed/products.xml")

    assert response.status_code == 200
    assert b"DEFAULT-1" in response.content
