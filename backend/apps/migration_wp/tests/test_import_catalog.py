import io
import json
import logging

import pytest
from django.core.management import call_command

from apps.catalog.models import Category, Product, Tag
from apps.reviews.models import Review

pytestmark = pytest.mark.django_db

IMPORT_CATALOG_LOGGER = "apps.migration_wp.management.commands.import_catalog"


def test_imports_categories_preserving_slug_and_legacy_id(artifact_path):
    call_command("import_catalog", str(artifact_path), "--skip-media")

    soaps = Category.objects.get(slug="body-soaps")
    assert soaps.name == "Body Soaps"
    assert soaps.legacy_wp_id == 21
    assert soaps.parent is None
    assert soaps.description == "Soaps for the body"
    # body-soaps, lotions, shea-butters (nested), orphan-cat (dangling parent)
    assert Category.objects.count() == 4


def test_nested_category_gets_parent_wired(artifact_path):
    call_command("import_catalog", str(artifact_path), "--skip-media")

    nested = Category.objects.get(slug="shea-butters")
    assert nested.parent is not None
    assert nested.parent.slug == "body-soaps"


def test_orphan_parent_reference_logs_warning_and_leaves_parent_none(artifact_path, caplog):
    out = io.StringIO()
    with caplog.at_level(logging.WARNING, logger=IMPORT_CATALOG_LOGGER):
        call_command("import_catalog", str(artifact_path), "--skip-media", stdout=out)

    orphan = Category.objects.get(slug="orphan-cat")
    assert orphan.parent is None
    assert any(
        "orphan-cat" in r.getMessage() and "999" in r.getMessage() for r in caplog.records
    )
    assert "orphan_parent_refs: 1" in out.getvalue()


def test_category_with_existing_slug_but_no_legacy_id_is_adopted(artifact_path):
    """A category slug that already exists (created by staff in wp-admin, or
    left over from an earlier partial run) with no legacy_wp_id must be
    adopted rather than causing a slug-uniqueness IntegrityError that aborts
    the categories-and-tags transaction together."""
    Category.objects.create(slug="body-soaps", name="Body Soaps (old)")

    call_command("import_catalog", str(artifact_path), "--skip-media")

    soaps = Category.objects.get(slug="body-soaps")
    assert soaps.legacy_wp_id == 21
    assert soaps.name == "Body Soaps"
    assert Category.objects.filter(slug="body-soaps").count() == 1
    # Tags must still have been imported -- proof the transaction wasn't aborted.
    assert Tag.objects.filter(slug="bestseller").exists()


def test_imports_tags(artifact_path):
    call_command("import_catalog", str(artifact_path), "--skip-media")
    tag = Tag.objects.get(slug="bestseller")
    assert tag.name == "bestseller"


def test_rerunning_updates_renamed_tag(artifact_path):
    """Regression guard: Tag has no legacy id, so a rename in WordPress between
    rehearsal and cutover must still propagate on a rerun."""
    call_command("import_catalog", str(artifact_path), "--skip-media")

    data = json.loads(artifact_path.read_text(encoding="utf-8"))
    for t in data["terms"]:
        if t["slug"] == "bestseller":
            t["name"] = "Best Seller (renamed)"
    artifact_path.write_text(json.dumps(data), encoding="utf-8")

    call_command("import_catalog", str(artifact_path), "--skip-media")

    tag = Tag.objects.get(slug="bestseller")
    assert tag.name == "Best Seller (renamed)"
    assert Tag.objects.filter(slug="bestseller").count() == 1


def test_dry_run_writes_nothing(artifact_path):
    call_command("import_catalog", str(artifact_path), "--dry-run")
    assert Category.objects.count() == 0
    assert Tag.objects.count() == 0


def test_rerunning_does_not_duplicate_categories(artifact_path):
    call_command("import_catalog", str(artifact_path), "--skip-media")
    call_command("import_catalog", str(artifact_path), "--skip-media")
    assert Category.objects.count() == 4
    assert Category.objects.filter(legacy_wp_id=21).count() == 1


def test_import_catalog_never_touches_mariadb():
    """The extract/import split is a security boundary: import must not be able
    to reach the WordPress database even if credentials were present."""
    import inspect

    from apps.migration_wp.management.commands import import_catalog

    source = inspect.getsource(import_catalog)
    assert "wp_reader" not in source
    assert "pymysql" not in source


def test_imports_product_with_cleaned_description_and_benefits(artifact_path):
    call_command("import_catalog", str(artifact_path), "--skip-media")

    p = Product.objects.get(slug="toke-scented-shea-butter")
    assert p.name == "Toke Scented Shea Butter"
    assert p.legacy_wp_id == 101
    assert p.legacy_source == "wp_ng"
    assert p.status == "active"
    assert "data-start" not in p.description
    assert "<h3>Benefits</h3>" in p.description
    assert "<li>Deeply moisturizes dry skin.</li>" in p.description
    assert p.short_description == "Daily shea butter."


def test_usps_and_testimonials_land_in_json_fields(artifact_path):
    call_command("import_catalog", str(artifact_path), "--skip-media")

    p = Product.objects.get(slug="toke-scented-shea-butter")
    assert p.usps == ["Daily hydration, all-day softness.", "Relieves eczema."]
    assert len(p.testimonials) == 1
    assert p.testimonials[0]["name"] == "Mayowa - Osogbo"
    assert p.testimonials[0]["qty_bought"] == 1


def test_testimonials_never_become_reviews_or_move_the_rating(artifact_path):
    """The source carries no rating. Inventing one would publish a fabricated
    schema.org aggregateRating via storefront/src/lib/seo.ts:154."""
    call_command("import_catalog", str(artifact_path), "--skip-media")

    p = Product.objects.get(slug="toke-scented-shea-butter")
    assert Review.objects.count() == 0
    assert p.rating_count == 0
    assert p.rating_avg == 0


def test_draft_product_imports_as_draft(artifact_path):
    call_command("import_catalog", str(artifact_path), "--skip-media")
    assert Product.objects.get(slug="toke-draft-item").status == "draft"


def test_product_in_multiple_categories_gets_all_of_them(artifact_path):
    call_command("import_catalog", str(artifact_path), "--skip-media")
    p = Product.objects.get(slug="toke-scented-shea-butter")
    assert sorted(p.categories.values_list("slug", flat=True)) == ["body-soaps", "lotions"]
    assert list(p.tags.values_list("slug", flat=True)) == ["bestseller"]


def test_ingredients_directions_warnings_are_blank(artifact_path):
    """No source field exists for these — a manual worklist, not a bug."""
    call_command("import_catalog", str(artifact_path), "--skip-media")
    p = Product.objects.get(slug="toke-scented-shea-butter")
    assert p.ingredients == ""
    assert p.directions == ""
    assert p.warnings == ""


def test_all_seven_products_import(artifact_path):
    call_command("import_catalog", str(artifact_path), "--skip-media")
    assert Product.objects.filter(legacy_source="wp_ng").count() == 7


def test_rerunning_does_not_duplicate_products(artifact_path):
    call_command("import_catalog", str(artifact_path), "--skip-media")
    call_command("import_catalog", str(artifact_path), "--skip-media")
    assert Product.objects.filter(legacy_source="wp_ng").count() == 7
    assert Product.objects.filter(legacy_wp_id=101).count() == 1


def test_product_with_existing_slug_but_no_legacy_id_is_adopted(artifact_path):
    """Mirrors the category adoption fallback: Product.slug is globally unique,
    so a pre-existing product with that slug (created in wp-admin, or left over
    from an earlier partial run) must be adopted rather than aborting the whole
    transaction with an IntegrityError."""
    Product.objects.create(slug="toke-scented-shea-butter", name="Old Name")

    call_command("import_catalog", str(artifact_path), "--skip-media")

    p = Product.objects.get(slug="toke-scented-shea-butter")
    assert p.legacy_wp_id == 101
    assert p.name == "Toke Scented Shea Butter"
    assert Product.objects.filter(slug="toke-scented-shea-butter").count() == 1
