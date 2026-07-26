"""Product import phase.

Moved out of the `import_catalog` management command unchanged (Part A of the
Task 11 refactor) -- no behaviour change intended.
"""
from __future__ import annotations

from datetime import datetime, timezone as dt_timezone

from apps.catalog.models import Category, Product, Tag
from apps.migration_wp.transform import (
    append_benefits,
    clean_description,
    parse_benefits,
    parse_testimonials,
    parse_usps,
)

from .common import LEGACY_SOURCE, logger

STATUS_MAP = {"publish": "active", "draft": "draft"}


def import_products(data) -> int:
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
            "status": STATUS_MAP.get(row["post_status"], "draft"),
            "published_at": _parse_dt(
                row.get("post_date_gmt"), wp_id=wp_id, slug=row["slug"]
            ),
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


def _parse_dt(value, *, wp_id, slug):
    """Parse WP's post_date_gmt, tolerating WordPress's unset-date sentinel.

    WordPress stores "0000-00-00 00:00:00" for an unset date -- truthy, so it
    passes a bare `if not value` guard and strptime then raises ValueError,
    which would abort the whole atomic import with a traceback that doesn't
    name the offending product. Treat anything unparseable as unknown (None,
    mirroring the weight/_grams "unknown, not a lie" approach) and warn with
    enough context (wp_id, slug) to act on it.
    """
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=dt_timezone.utc
        )
    except ValueError:
        logger.warning(
            "Unparseable post_date_gmt %r for product wp_id=%s slug=%r -- "
            "published_at left null",
            value, wp_id, slug,
        )
        return None
