import io
import json
import logging
from decimal import Decimal

import pytest
from django.core.management import call_command

from apps.catalog.models import Category, Product, ProductVariant, Tag
from apps.pricing.models import Price
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
    to reach the WordPress database even if credentials were present.

    The import phases were split out of this command into the
    apps.migration_wp.importers package (Part A of the Task 11 refactor). If
    this test only inspected the now-thin orchestrator, it would no longer
    actually verify the boundary -- the real work (and any future MariaDB
    reach-in) lives in the importer modules. So it walks every module in the
    importers package too. This is a strengthening of the guarantee, not a
    weakening of the test.
    """
    import importlib
    import inspect
    import pkgutil

    from apps.migration_wp import importers
    from apps.migration_wp.management.commands import import_catalog

    sources = [inspect.getsource(import_catalog)]
    for module_info in pkgutil.walk_packages(importers.__path__, importers.__name__ + "."):
        module = importlib.import_module(module_info.name)
        sources.append(inspect.getsource(module))

    for source in sources:
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


def test_simple_product_gets_one_default_variant_with_generated_sku(artifact_path):
    call_command("import_catalog", str(artifact_path), "--skip-media")
    p = Product.objects.get(slug="toke-scented-shea-butter")
    variants = list(p.variants.all())
    assert len(variants) == 1
    assert variants[0].sku == "TC-WP-101"
    assert variants[0].is_default is True


def test_existing_sku_is_preserved(artifact_path):
    call_command("import_catalog", str(artifact_path), "--skip-media")
    assert Product.objects.get(slug="toke-coconut-oil").variants.get().sku == "TOKE-COCO"


def test_variable_product_gets_one_variant_per_variation_keyed_on_variation_id(artifact_path):
    """Keying on the parent ID would collide both variations into one."""
    call_command("import_catalog", str(artifact_path), "--skip-media")
    p = Product.objects.get(slug="toke-body-lotion")
    assert sorted(p.variants.values_list("sku", flat=True)) == ["TC-WP-5001", "TC-WP-5002"]


def test_variant_option_values_use_term_names_across_all_axes(artifact_path):
    call_command("import_catalog", str(artifact_path), "--skip-media")
    v = ProductVariant.objects.get(sku="TC-WP-5001")
    assert v.option_values == {
        "Product Size": "100 ml",
        "Price Options": "Single",
        "Shea Variant": "Unscented",
    }


def test_weight_converts_kilograms_to_grams(artifact_path):
    """WooCommerce stores kg; ProductVariant.weight_grams is an integer of grams.
    delivery/services.py sums this to price delivery, so a wrong unit is a
    silently wrong shipping quote."""
    call_command("import_catalog", str(artifact_path), "--skip-media")
    assert ProductVariant.objects.get(sku="TC-WP-101").weight_grams == 266
    assert ProductVariant.objects.get(sku="TOKE-COCO").weight_grams == 1500
    assert ProductVariant.objects.get(sku="TC-WP-5001").weight_grams == 400


def test_missing_weight_is_null_not_zero(artifact_path):
    """Null means unknown; 0 would be a lie that delivery pricing would trust."""
    call_command("import_catalog", str(artifact_path), "--skip-media")
    assert ProductVariant.objects.get(sku="TC-WP-5002").weight_grams is None


def test_regular_price_creates_one_ngn_price(artifact_path):
    call_command("import_catalog", str(artifact_path), "--skip-media")
    price = ProductVariant.objects.get(sku="TC-WP-101").prices.get()
    assert price.amount == Decimal("5000.00")
    assert price.currency_id == "NGN"
    assert price.starts_at is None


def test_sale_price_creates_a_second_dated_row_with_compare_at(artifact_path):
    call_command("import_catalog", str(artifact_path), "--skip-media")
    v = ProductVariant.objects.get(sku="TC-WP-104")
    sale = v.prices.exclude(starts_at=None).get()
    assert sale.amount == Decimal("1500.00")
    assert sale.compare_at_amount == Decimal("2000.00")
    assert sale.starts_at is not None
    assert sale.ends_at is not None
    assert v.prices.count() == 2


def test_prices_do_not_duplicate_on_rerun(artifact_path):
    """Postgres treats NULL starts_at as distinct, so the unique constraint alone
    does NOT protect against this. Delete-and-recreate is what makes it safe."""
    call_command("import_catalog", str(artifact_path), "--skip-media")
    call_command("import_catalog", str(artifact_path), "--skip-media")
    assert ProductVariant.objects.get(sku="TC-WP-101").prices.count() == 1
    assert Price.objects.filter(variant__sku="TC-WP-104").count() == 2


def test_variants_do_not_duplicate_on_rerun(artifact_path):
    call_command("import_catalog", str(artifact_path), "--skip-media")
    call_command("import_catalog", str(artifact_path), "--skip-media")
    assert ProductVariant.objects.count() == 8


def test_orphaned_variant_is_deactivated_not_deleted_and_default_stays_singular(artifact_path):
    """If a variation is removed from WooCommerce between runs (or its _sku changes,
    which orphans the old row the same way), its ProductVariant must not be deleted
    -- historical order items may reference it -- and must not keep is_default=True
    forever, or a product can end up with two default variants at once."""
    call_command("import_catalog", str(artifact_path), "--skip-media")

    data = json.loads(artifact_path.read_text(encoding="utf-8"))
    data["variations"] = [v for v in data["variations"] if v["ID"] != 5002]
    del data["meta"]["5002"]
    artifact_path.write_text(json.dumps(data), encoding="utf-8")

    out = io.StringIO()
    call_command("import_catalog", str(artifact_path), "--skip-media", stdout=out)

    p = Product.objects.get(slug="toke-body-lotion")
    orphan = ProductVariant.objects.get(sku="TC-WP-5002")
    assert orphan.is_active is False
    assert orphan.is_default is False
    assert p.variants.filter(is_default=True).count() == 1
    assert "orphan_variants: 1" in out.getvalue()


def test_unparseable_post_date_does_not_abort_import(artifact_path):
    """WordPress stores "0000-00-00 00:00:00" for unset dates -- truthy, so it must
    not silently raise ValueError and abort the whole atomic import."""
    data = json.loads(artifact_path.read_text(encoding="utf-8"))
    for row in data["products"]:
        if row["ID"] == 106:
            row["post_date_gmt"] = "0000-00-00 00:00:00"
    artifact_path.write_text(json.dumps(data), encoding="utf-8")

    call_command("import_catalog", str(artifact_path), "--skip-media")

    p = Product.objects.get(slug="toke-draft-item")
    assert p.published_at is None
    assert Product.objects.filter(legacy_source="wp_ng").count() == 7


def test_diverging_existing_price_logs_a_warning(artifact_path, caplog):
    """No provenance marker on Price means a human-edited amount looks identical
    to a migrated one -- the warning is the only audit trail available."""
    call_command("import_catalog", str(artifact_path), "--skip-media")

    variant = ProductVariant.objects.get(sku="TC-WP-101")
    price = variant.prices.get()
    price.amount = Decimal("9999.00")
    price.save()

    with caplog.at_level(logging.WARNING, logger=IMPORT_CATALOG_LOGGER):
        call_command("import_catalog", str(artifact_path), "--skip-media")

    assert any(
        "TC-WP-101" in r.getMessage() and "9999.00" in r.getMessage()
        for r in caplog.records
    )
    # The migrated value still wins when the flag isn't used -- this is an audit
    # trail, not a block.
    assert ProductVariant.objects.get(sku="TC-WP-101").prices.get().amount == Decimal("5000.00")


def test_skip_prices_leaves_existing_prices_untouched(artifact_path):
    call_command("import_catalog", str(artifact_path), "--skip-media")

    variant = ProductVariant.objects.get(sku="TC-WP-101")
    price = variant.prices.get()
    price.amount = Decimal("9999.00")
    price.save()

    call_command("import_catalog", str(artifact_path), "--skip-media", "--skip-prices")

    assert ProductVariant.objects.get(sku="TC-WP-101").prices.get().amount == Decimal("9999.00")
    # Products and variants still import/update normally -- only pricing is skipped.
    assert Product.objects.filter(legacy_source="wp_ng").count() == 7
    assert ProductVariant.objects.count() == 8


def test_grams_upper_bound_logs_warning_but_does_not_clamp(artifact_path, caplog):
    """A data-entry error like _weight="99999" becomes 99,999,000g and would
    silently feed shipping pricing -- make it visible, don't guess a fix."""
    data = json.loads(artifact_path.read_text(encoding="utf-8"))
    data["meta"]["102"]["_weight"] = "99999"
    artifact_path.write_text(json.dumps(data), encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger=IMPORT_CATALOG_LOGGER):
        call_command("import_catalog", str(artifact_path), "--skip-media")

    v = ProductVariant.objects.get(sku="TOKE-COCO")
    assert v.weight_grams == 99999000
    assert any("TOKE-COCO" in r.getMessage() for r in caplog.records)
