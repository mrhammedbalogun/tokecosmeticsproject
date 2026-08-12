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
    "sku", "variant_name", "weight_grams", "price_ngn", "price_gbp", "price_usd", "price_cad",
]
# weight_grams bounds mirror the admin editor's (admin/src/lib/variant-weight.ts):
# whole grams, at least 1 — a 0 is a claim a courier quote would be built from, not an
# absence — and at most a tonne, which catches "2500000" typed for "2500".
_WEIGHT_MAX_GRAMS = 1_000_000
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

    defaults = {"product": product, "name": row.get("variant_name") or sku, "is_default": True}
    # A BLANK weight leaves whatever the variant already has — a spreadsheet exported
    # before this column existed (or with the cell simply not filled in) must not wipe
    # weights on re-import. There is deliberately no CSV way to CLEAR a weight; that is
    # a one-off act for the editor, not a bulk operation.
    weight_raw = (row.get("weight_grams") or "").strip()
    if weight_raw:
        try:
            weight = int(weight_raw)
        except ValueError as exc:
            raise ValueError(f"weight_grams is not whole grams: {weight_raw!r}") from exc
        if not 1 <= weight <= _WEIGHT_MAX_GRAMS:
            raise ValueError(
                f"weight_grams must be between 1 and {_WEIGHT_MAX_GRAMS} grams: {weight_raw!r}"
            )
        defaults["weight_grams"] = weight

    variant, _ = ProductVariant.objects.update_or_create(sku=sku, defaults=defaults)

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
                # Blank, never 0, for a variant with no recorded weight — same rule as
                # everywhere else weight appears.
                "weight_grams": (
                    "" if variant is None or variant.weight_grams is None else variant.weight_grams
                ),
                "price_ngn": prices.get("NGN", ""),
                "price_gbp": prices.get("GBP", ""),
                "price_usd": prices.get("USD", ""),
                "price_cad": prices.get("CAD", ""),
            }
        )
    return buf.getvalue()
