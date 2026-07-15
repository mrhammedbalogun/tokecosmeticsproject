"""Pure product CSV import/export. No request/HTTP here — testable in isolation."""
from __future__ import annotations

import csv
import io
from decimal import Decimal, InvalidOperation

from django.db import transaction

from apps.catalog.models import Brand, Category, Product, ProductVariant
from apps.core.models import Currency
from apps.pricing.models import Price

COLUMNS = [
    "slug", "name", "brand_slug", "status", "short_description", "category_slugs",
    "sku", "variant_name", "price_ngn", "price_gbp", "price_usd", "price_cad",
]
_PRICE_COLS = {"price_ngn": "NGN", "price_gbp": "GBP", "price_usd": "USD", "price_cad": "CAD"}


def _apply_row(row: dict) -> str:
    slug = (row.get("slug") or "").strip()
    sku = (row.get("sku") or "").strip()
    if not slug or not row.get("name"):
        raise ValueError("slug and name are required")
    if not sku:
        raise ValueError("sku is required")

    brand = None
    if row.get("brand_slug"):
        brand, _ = Brand.objects.get_or_create(
            slug=row["brand_slug"].strip(), defaults={"name": row["brand_slug"].strip()}
        )

    product, created = Product.objects.update_or_create(
        slug=slug,
        defaults={
            "name": row["name"],
            "brand": brand,
            "status": (row.get("status") or "draft").strip() or "draft",
            "short_description": row.get("short_description") or "",
        },
    )
    if row.get("category_slugs"):
        cats = []
        for cslug in filter(None, (s.strip() for s in row["category_slugs"].split("|"))):
            cat, _ = Category.objects.get_or_create(slug=cslug, defaults={"name": cslug})
            cats.append(cat)
        product.categories.set(cats)

    variant, _ = ProductVariant.objects.update_or_create(
        sku=sku,
        defaults={"product": product, "name": row.get("variant_name") or sku, "is_default": True},
    )

    for col, code in _PRICE_COLS.items():
        raw = (row.get(col) or "").strip()
        if not raw:
            continue
        try:
            amount = Decimal(raw)
        except InvalidOperation as exc:
            raise ValueError(f"{col} is not a number: {raw!r}") from exc
        Price.objects.update_or_create(
            variant=variant,
            currency=Currency.objects.get(code=code),
            country=None,
            starts_at=None,
            defaults={"amount": amount},
        )
    return "created" if created else "updated"


def import_products_csv(rows) -> dict:
    """Apply an iterable of row dicts. Each row is its own transaction so one bad
    row doesn't roll back the good ones. Returns {created, updated, errors:[{row, error}]}.
    Row numbers are 1-based over the data rows (header excluded)."""
    report = {"created": 0, "updated": 0, "errors": []}
    for i, row in enumerate(rows, start=1):
        try:
            with transaction.atomic():
                outcome = _apply_row(row)
            report[outcome] += 1
        except Exception as exc:  # noqa: BLE001 — collect, don't abort the batch
            report["errors"].append({"row": i, "error": str(exc)})
    return report


def parse_csv_bytes(data: bytes) -> list[dict]:
    return list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))


def export_products_csv() -> str:
    """Serialize every product's default variant to CSV text."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=COLUMNS)
    writer.writeheader()
    products = Product.objects.select_related("brand").prefetch_related(
        "categories", "variants__prices__currency"
    )
    for p in products:
        variant = p.variants.filter(is_default=True).first() or p.variants.first()
        prices = {}
        if variant:
            for pr in variant.prices.filter(country__isnull=True):
                prices[pr.currency.code] = str(pr.amount)
        writer.writerow(
            {
                "slug": p.slug,
                "name": p.name,
                "brand_slug": p.brand.slug if p.brand else "",
                "status": p.status,
                "short_description": p.short_description,
                "category_slugs": "|".join(c.slug for c in p.categories.all()),
                "sku": variant.sku if variant else "",
                "variant_name": variant.name if variant else "",
                "price_ngn": prices.get("NGN", ""),
                "price_gbp": prices.get("GBP", ""),
                "price_usd": prices.get("USD", ""),
                "price_cad": prices.get("CAD", ""),
            }
        )
    return buf.getvalue()
