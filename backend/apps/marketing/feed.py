"""The product catalogue as a Google Shopping feed — one document, four consumers.

── WHY ONE FEED AND NOT FOUR ───────────────────────────────────────────────────────────

Meta, TikTok and Snapchat all accept Google's Merchant Center RSS 2.0 schema for a
product catalogue, and each of them documents it as a supported format. Writing three
more feeds in three more shapes would triple the surface on which the ONE thing that
actually matters can go wrong.

That one thing is `<g:id>`. It must equal the `content_id` the pixel and the Conversions
API send, or dynamic retargeting silently does nothing — the visitor looked at product
`TOKE-SER-50`, the platform is asked to show them product `1417`, and it shows them
nothing. No error is raised anywhere in that chain. So the id here is `ProductVariant.sku`,
the same string `apps/marketing/events._contents` sends and the same one the browser
pixel puts in `content_ids`.

── WHY IT IS PER-MARKET ────────────────────────────────────────────────────────────────

Prices, currency and availability are all per-country in this shop: a variant may be
₦12,000 in Nigeria, £9 in the UK, and unsellable in Canada because no warehouse serving
Canada holds it. A single feed would have to pick one of those and be wrong for three
markets. So the feed takes `?country=NG` and each ad account subscribes to the feed for
the market it advertises in.

── WHAT IS DELIBERATELY LEFT OUT ───────────────────────────────────────────────────────

`g:google_product_category` and `g:gtin`. The shop has neither a Google taxonomy mapping
nor barcodes on its own-brand products, and a fabricated value in either field is worse
than an absent one: Google rejects a wrong taxonomy id outright, and an invented GTIN
puts the whole account at risk. Both become worth adding the day the data exists.
"""
from __future__ import annotations

from xml.sax.saxutils import escape

from django.conf import settings

from apps.catalog.images import storage_url
from apps.catalog.models import Product
from apps.pricing.services import resolve_price

# 5,000 variants is far beyond anything this catalogue holds (the WordPress import
# brought across a few hundred products) and is a backstop rather than a policy: a feed
# is generated on request, and an unbounded query behind a public URL is a way to be
# knocked over politely.
MAX_ITEMS = 5000


def _site_url() -> str:
    return (getattr(settings, "FRONTEND_URL", "") or "https://tokecosmetics.com").rstrip("/")


def _availability(variant, country) -> str:
    """Google's vocabulary: `in stock` / `out of stock`.

    Computed from the warehouses that actually SERVE this country, which is the same
    rule `catalog.services.annotate_in_stock` applies to the storefront. A feed that
    advertises Nigerian stock to a British shopper produces clicks that cannot convert,
    which is the expensive kind of wrong.
    """
    from django.db.models import F

    from apps.inventory.models import StockItem

    has_stock = StockItem.objects.filter(
        variant=variant,
        warehouse__is_active=True,
        warehouse__serves_countries=country,
        quantity__gt=F("reserved"),
    ).exists()
    return "in stock" if has_stock else "out of stock"


def _image_for(product, variant) -> str:
    """The variant's own picture, else the product's first.

    A product with NO image at all still gets an item, and that asymmetry with the
    unpriced-variant rule above is deliberate. An unpriced variant is hidden from the
    storefront too — "hide until priced" is a shop decision, and the feed simply agrees
    with it. A missing image is not a decision, it is a gap in the catalogue, and every
    platform reports it as an item-level error naming the product. Dropping the row
    instead would make that gap invisible, and the product would silently never be
    advertised while the feed looked perfectly healthy.
    """
    image = product.images.filter(variant=variant).first() or product.images.first()
    return storage_url(image.image.name) if image else ""


def _tag(name: str, value: str) -> str:
    return f"<{name}>{escape(value)}</{name}>" if value else ""


def _item(product, variant, price, country) -> str:
    site = _site_url()
    # A description is required. Falling back through short_description to the product
    # name keeps every sellable variant IN the feed: an item dropped for a missing
    # description is a product that can never be retargeted, which is a bigger loss than
    # a thin description.
    description = (product.short_description or product.description or product.name)[:5000]
    title = f"{product.name} — {variant.name}" if variant.name else product.name

    parts = [
        # THE CONTRACT. Same string as the pixel's `content_ids` and the Conversions
        # API's `content_id`. See the module docstring.
        _tag("g:id", variant.sku),
        _tag("g:title", title[:150]),
        _tag("g:description", description),
        _tag("g:link", f"{site}/product/{product.slug}"),
        _tag("g:image_link", _image_for(product, variant)),
        _tag("g:availability", _availability(variant, country)),
        # "12000.00 NGN" — amount, space, ISO currency. Google rejects a bare number.
        _tag("g:price", f"{price.amount} {price.currency}"),
        _tag("g:condition", "new"),
        _tag("g:brand", product.brand.name if product.brand else "Toke Cosmetics"),
        # Ties a product's variants together so a platform shows ONE product with
        # shades/sizes rather than eight near-identical listings.
        _tag("g:item_group_id", product.slug),
    ]
    if price.compare_at and price.compare_at > price.amount:
        # `g:price` is the was-price and `g:sale_price` the now-price — that way round,
        # which is the opposite of how it reads. Getting it backwards advertises the
        # higher number as the offer.
        parts[6] = _tag("g:price", f"{price.compare_at} {price.currency}")
        parts.append(_tag("g:sale_price", f"{price.amount} {price.currency}"))

    return "<item>" + "".join(p for p in parts if p) + "</item>"


def build_feed(country) -> str:
    """The whole document for one market."""
    site = _site_url()
    products = (
        # "active", NOT "published" — `Product.STATUS` is draft/active/archived. This
        # read `status="published"` for one commit, which is a status no product has
        # ever held, so the feed was an empty document that every platform would have
        # accepted without complaint.
        Product.objects.filter(status="active")
        .select_related("brand")
        .prefetch_related("variants", "images", "available_countries")
        .order_by("id")
    )

    items: list[str] = []
    for product in products:
        allowed = list(product.available_countries.all())
        # Same visibility rule as the storefront (`catalog.services.sellable_in`): a
        # product restricted to other markets must not be advertised into this one.
        if allowed and country not in allowed:
            continue
        for variant in product.variants.all():
            if not variant.is_active or not variant.sku:
                continue
            price = resolve_price(variant, country)
            # "Hide until priced", exactly as the storefront does. A feed item with no
            # price is rejected anyway; skipping it here keeps the reason ours.
            if price is None:
                continue
            items.append(_item(product, variant, price, country))
            if len(items) >= MAX_ITEMS:
                break
        if len(items) >= MAX_ITEMS:
            break

    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0" xmlns:g="http://base.google.com/ns/1.0"><channel>'
        f"<title>Toke Cosmetics</title><link>{escape(site)}</link>"
        f"<description>Toke Cosmetics product catalogue ({escape(country.code)})</description>"
        + "".join(items)
        + "</channel></rss>"
    )
