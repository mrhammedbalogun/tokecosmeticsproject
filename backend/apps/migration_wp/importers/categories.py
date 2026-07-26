"""Category and tag import phase.

Moved out of the `import_catalog` management command unchanged (Part A of the
Task 11 refactor) -- no behaviour change intended.
"""
from __future__ import annotations

from apps.catalog.models import Category, Tag

from .common import logger


def import_categories(data) -> tuple[int, int]:
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


def tag_skip_reason(term) -> str | None:
    """Why this product_tag must not become a Tag, or None if it's fine.

    WooCommerce's tag box was used as an Instagram caption field. 83 of the 137
    live product_tag terms are hashtag dumps pasted in as a single term, e.g.
    "#AcneCareRoutine #AcneFreeSkin #PimpleFreeSkin #BreakoutControl ...". Each
    blob is unique, so it matches exactly one product and is worthless for
    filtering; several run to 200 characters.

    The filter is the '#' marker, NOT length. Only 21 of the 83 overflow
    Tag.name's varchar(100) -- filtering on length would have let the other 62
    blobs through, and the first sign of trouble would have been junk in the
    admin's tag list. Length is still checked second, because a term that
    overflows without a '#' is unexpected junk that would otherwise abort the
    whole import with a DataError at the database layer.
    """
    name = term.get("name") or ""
    slug = term.get("slug") or ""
    if "#" in name:
        return "hashtag blob — re-tag by hand in WooCommerce, then re-import"
    name_max = Tag._meta.get_field("name").max_length
    slug_max = Tag._meta.get_field("slug").max_length
    if len(name) > name_max or len(slug) > slug_max:
        return f"too long (name {len(name)}/{name_max}, slug {len(slug)}/{slug_max})"
    return None


def import_tags(data) -> tuple[int, list[dict]]:
    """WP product_tag terms -> Tag, keyed on slug.

    Tag has no legacy_wp_id, so slug is the only stable identity we have.
    update_or_create (not get_or_create) so a tag renamed in WordPress
    between rehearsal and cutover has its name refreshed here too, instead
    of being created once and left stale forever.

    Returns (imported_count, skipped) -- see tag_skip_reason. Skipped terms are
    reported, never truncated: a truncated tag is a *different* tag that would
    then be indistinguishable from a real one on the next run.
    """
    terms = [t for t in data["terms"] if t["taxonomy"] == "product_tag"]
    imported = 0
    skipped: list[dict] = []
    for t in terms:
        reason = tag_skip_reason(t)
        if reason:
            logger.warning("Skipping product_tag %r: %s", (t.get("name") or "")[:60], reason)
            skipped.append({**t, "skip_reason": reason})
            continue
        Tag.objects.update_or_create(slug=t["slug"], defaults={"name": t["name"]})
        imported += 1
    return imported, skipped
