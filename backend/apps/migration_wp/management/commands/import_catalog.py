"""Import a catalogue artifact into Postgres. Never opens a MariaDB connection.

Idempotent by design — see the per-object keys in the Plan-21 spec. Safe to run
repeatedly (dry run, rehearsal, cutover).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.catalog.models import Category, Product, ProductVariant, Tag
from apps.core.models import Currency
from apps.migration_wp.transform import (
    append_benefits,
    clean_description,
    generate_sku,
    parse_benefits,
    parse_option_values,
    parse_testimonials,
    parse_usps,
)
from apps.pricing.models import Price

LEGACY_SOURCE = "wp_ng"

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """Import a catalogue JSON artifact produced by extract_wp_catalog.

    Dry-run contract: `--dry-run` rolls back the database via transaction.set_rollback,
    but that covers ORM writes ONLY. Any operation with side effects outside Postgres —
    S3 uploads, email, HTTP calls, filesystem writes — MUST check `self.dry_run` and
    skip before acting. A dry run that mutates external state is a broken review gate.
    """

    help = "Import a catalogue JSON artifact produced by extract_wp_catalog."

    def add_arguments(self, parser):
        parser.add_argument("artifact", help="path to catalog-export.json")
        parser.add_argument("--dry-run", action="store_true", help="report only, write nothing")
        parser.add_argument("--skip-media", action="store_true", help="skip S3 image upload")
        parser.add_argument("--skip-stock", action="store_true", help="skip the stock phase")
        parser.add_argument(
            "--force-stock",
            action="store_true",
            help="overwrite stock a human has edited (dangerous — see spec)",
        )
        parser.add_argument(
            "--uploads-root",
            default="/mnt/wp-uploads-ng",
            help="read-only mount of wp-content/uploads",
        )

    def handle(self, *args, **options):
        self.dry_run = options["dry_run"]
        data = json.loads(Path(options["artifact"]).read_text(encoding="utf-8"))

        if self.dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no writes will be made"))

        with transaction.atomic():
            cats, orphans = self._import_categories(data)
            tags = self._import_tags(data)
            products = self._import_products(data)
            variants = self._import_variants_and_prices(data)
            self.stdout.write(
                f"categories: {cats}  tags: {tags}  orphan_parent_refs: {orphans}  "
                f"products: {products}  variants: {variants}"
            )
            if self.dry_run:
                transaction.set_rollback(True)

    def _import_categories(self, data) -> tuple[int, int]:
        """WP product_cat terms -> Category, keyed on legacy_wp_id, slug preserved.

        A category is matched by legacy_wp_id first. If no row carries that WP
        term id yet, fall back to a slug match — the same category may already
        exist (created by staff in wp-admin, or left over from an earlier
        partial run) without the legacy id attached, and Category.slug is
        globally unique so blindly inserting would raise IntegrityError and
        abort the whole transaction. A slug match is *adopted*: its
        legacy_wp_id is set and its fields are refreshed from the artifact.
        Adoption is logged at INFO so the merge is never silent.

        Returns (category_count, orphan_parent_ref_count).
        """
        terms = [t for t in data["terms"] if t["taxonomy"] == "product_cat"]
        by_wp_id: dict[int, Category] = {}
        # First pass: create/update without parents so any input order works.
        for t in terms:
            term_id = t["term_id"]
            fields = {
                "name": t["name"],
                "slug": t["slug"],
                "description": t.get("description") or "",
            }
            cat = Category.objects.filter(legacy_wp_id=term_id).first()
            if cat is None:
                cat = Category.objects.filter(slug=t["slug"]).first()
                if cat is not None:
                    logger.info(
                        "Adopting existing category slug=%r (id=%s) into WP term_id=%s",
                        t["slug"], cat.pk, term_id,
                    )
                    cat.legacy_wp_id = term_id
            if cat is None:
                cat = Category(legacy_wp_id=term_id)
            for field, value in fields.items():
                setattr(cat, field, value)
            cat.save()
            by_wp_id[term_id] = cat

        # Second pass: wire parents now that every term in this artifact has a
        # row. A parent id that isn't in the artifact at all (deleted upstream,
        # or a data error) must not be silently dropped -- warn, count it, and
        # leave the child parentless so the dry-run summary surfaces it rather
        # than burying it in logs.
        orphan_count = 0
        for t in terms:
            parent_wp_id = t.get("parent") or 0
            if not parent_wp_id:
                continue
            parent = by_wp_id.get(parent_wp_id)
            if parent is None:
                orphan_count += 1
                logger.warning(
                    "Category %r (WP term_id=%s) references missing parent "
                    "WP term_id=%s; leaving parent unset",
                    t["slug"], t["term_id"], parent_wp_id,
                )
                continue
            cat = by_wp_id[t["term_id"]]
            cat.parent = parent
            cat.save(update_fields=["parent"])
        return len(terms), orphan_count

    def _import_tags(self, data) -> int:
        """WP product_tag terms -> Tag, keyed on slug.

        Tag has no legacy_wp_id, so slug is the only stable identity we have.
        update_or_create (not get_or_create) so a tag renamed in WordPress
        between rehearsal and cutover has its name refreshed here too, instead
        of being created once and left stale forever.
        """
        terms = [t for t in data["terms"] if t["taxonomy"] == "product_tag"]
        for t in terms:
            Tag.objects.update_or_create(slug=t["slug"], defaults={"name": t["name"]})
        return len(terms)

    STATUS_MAP = {"publish": "active", "draft": "draft"}

    def _import_products(self, data) -> int:
        """WP posts (post_type=product) -> Product, keyed on (legacy_source, legacy_wp_id).

        Same slug-adoption fallback as categories: Product.slug is globally
        unique, so a pre-existing product with that slug (staff-created, or
        left over from an earlier partial run) must be adopted -- its legacy
        fields set and refreshed -- rather than raising IntegrityError and
        aborting the whole transaction. Adoption is logged at INFO.
        """
        meta_all = data["meta"]
        links_by_object: dict[int, list[dict]] = {}
        for link in data["term_links"]:
            links_by_object.setdefault(link["object_id"], []).append(link)

        cats_by_wp_id = {
            c.legacy_wp_id: c for c in Category.objects.exclude(legacy_wp_id=None)
        }
        tags_by_slug = {t.slug: t for t in Tag.objects.all()}

        count = 0
        for row in data["products"]:
            wp_id = row["ID"]
            meta = meta_all.get(str(wp_id), {})

            description = clean_description(row.get("post_content"))
            description = append_benefits(description, parse_benefits(meta.get("Benefits")))

            fields = {
                "name": row["post_title"],
                "slug": row["slug"],
                "description": description,
                "short_description": clean_description(row.get("post_excerpt")),
                "status": self.STATUS_MAP.get(row["post_status"], "draft"),
                "published_at": self._parse_dt(row.get("post_date_gmt")),
                "usps": parse_usps(meta),
                "testimonials": parse_testimonials(meta),
            }

            product = Product.objects.filter(
                legacy_source=LEGACY_SOURCE, legacy_wp_id=wp_id
            ).first()
            if product is None:
                product = Product.objects.filter(slug=row["slug"]).first()
                if product is not None:
                    logger.info(
                        "Adopting existing product slug=%r (id=%s) into WP id=%s",
                        row["slug"], product.pk, wp_id,
                    )
                    product.legacy_source = LEGACY_SOURCE
                    product.legacy_wp_id = wp_id
            if product is None:
                product = Product(legacy_source=LEGACY_SOURCE, legacy_wp_id=wp_id)
            for field, value in fields.items():
                setattr(product, field, value)
            product.save()

            links = links_by_object.get(wp_id, [])
            product.categories.set(
                [
                    cats_by_wp_id[link["term_id"]]
                    for link in links
                    if link["taxonomy"] == "product_cat" and link["term_id"] in cats_by_wp_id
                ]
            )
            product.tags.set(
                [
                    tags_by_slug[link["slug"]]
                    for link in links
                    if link["taxonomy"] == "product_tag" and link["slug"] in tags_by_slug
                ]
            )
            count += 1
        return count

    @staticmethod
    def _parse_dt(value):
        if not value:
            return None
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=dt_timezone.utc
        )

    def _import_variants_and_prices(self, data) -> int:
        """WP variations (or the product itself, if simple) -> ProductVariant + Price.

        `sku` is the idempotency key for ProductVariant -- it has no legacy_wp_id.
        A variation's SKU MUST derive from the variation's own post ID, never the
        parent's, or every variable product's variations collide into one row.
        """
        meta_all = data["meta"]
        ngn = Currency.objects.get(code="NGN")

        term_names = {
            (t["taxonomy"], t["slug"]): t["name"]
            for t in data["terms"]
            if t["taxonomy"].startswith("pa_")
        }
        variations_by_parent: dict[int, list[dict]] = {}
        for v in data["variations"]:
            variations_by_parent.setdefault(v["post_parent"], []).append(v)

        products_by_wp_id = {
            p.legacy_wp_id: p for p in Product.objects.filter(legacy_source=LEGACY_SOURCE)
        }

        count = 0
        for row in data["products"]:
            wp_id = row["ID"]
            product = products_by_wp_id.get(wp_id)
            if product is None:
                continue
            children = variations_by_parent.get(wp_id, [])

            if children:
                for position, child in enumerate(children):
                    cmeta = meta_all.get(str(child["ID"]), {})
                    attrs = {k: v for k, v in cmeta.items() if k.startswith("attribute_")}
                    variant = self._upsert_variant(
                        product=product,
                        sku=generate_sku(cmeta.get("_sku"), child["ID"]),
                        name=child["post_title"].split(" - ")[-1],
                        option_values=parse_option_values(attrs, term_names),
                        weight_grams=self._grams(cmeta.get("_weight")),
                        is_default=(position == 0),
                        position=position,
                    )
                    self._rewrite_prices(variant, cmeta, ngn)
                    count += 1
            else:
                pmeta = meta_all.get(str(wp_id), {})
                variant = self._upsert_variant(
                    product=product,
                    sku=generate_sku(pmeta.get("_sku"), wp_id),
                    name="Default",
                    option_values={},
                    weight_grams=self._grams(pmeta.get("_weight")),
                    is_default=True,
                    position=0,
                )
                self._rewrite_prices(variant, pmeta, ngn)
                count += 1
        return count

    @staticmethod
    def _upsert_variant(*, product, sku, name, option_values, weight_grams, is_default, position):
        variant, _ = ProductVariant.objects.update_or_create(
            sku=sku,
            defaults={
                "product": product,
                "name": name,
                "option_values": option_values,
                "weight_grams": weight_grams,
                "is_default": is_default,
                "position": position,
            },
        )
        return variant

    def _rewrite_prices(self, variant, meta, currency) -> None:
        """Delete-and-recreate, NOT update-or-skip.

        The unique constraint is (variant, currency, country, starts_at); Postgres
        treats NULL starts_at as distinct, so update-or-skip would stack a fresh
        base price on every run without ever raising.
        """
        regular = self._decimal(meta.get("_regular_price"))
        if regular is None:
            return

        variant.prices.filter(currency=currency, country__isnull=True).delete()
        Price.objects.create(variant=variant, currency=currency, amount=regular)

        sale = self._decimal(meta.get("_sale_price"))
        if sale is None:
            return
        Price.objects.create(
            variant=variant,
            currency=currency,
            amount=sale,
            compare_at_amount=regular,
            starts_at=self._epoch(meta.get("_sale_price_dates_from")),
            ends_at=self._epoch(meta.get("_sale_price_dates_to")),
        )

    @staticmethod
    def _decimal(raw):
        if raw is None or str(raw).strip() == "":
            return None
        try:
            return Decimal(str(raw)).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            return None

    @staticmethod
    def _grams(raw):
        """WooCommerce _weight is in kilograms for this store. Returns None (unknown)
        rather than 0 for missing/invalid -- 0 would be a lie delivery pricing trusts."""
        if raw is None or str(raw).strip() == "":
            return None
        try:
            grams = int(round(float(str(raw).strip()) * 1000))
        except (TypeError, ValueError):
            return None
        return grams if grams > 0 else None

    @staticmethod
    def _epoch(raw):
        if not raw or not str(raw).strip().isdigit():
            return None
        return datetime.fromtimestamp(int(raw), tz=dt_timezone.utc)
