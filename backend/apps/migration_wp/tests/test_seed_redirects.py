"""seed_redirects: the rows, the editorial import, and the report that catches a redirect
pointing at a page nobody has written yet."""

from io import StringIO
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command

from apps.catalog.models import Category
from apps.cms.models import Page
from apps.core.models import Redirect

pytestmark = pytest.mark.django_db

ARTIFACT = str(Path(__file__).parent / "fixtures" / "urls-legacy.json")


def seed(*args):
    out = StringIO()
    call_command("seed_redirects", ARTIFACT, *args, stdout=out, stderr=out)
    return out.getvalue()


def test_it_seeds_the_rows():
    seed()
    assert Redirect.objects.get(old_path="/our-story").new_path == "/page/our-story"
    assert Redirect.objects.get(old_path="/my-account").new_path == "/account"
    assert Redirect.objects.get(old_path="/product-tag/shea-butter").new_path == (
        "/products?tag=shea-butter"
    )


def test_A_CATEGORY_THAT_DID_NOT_SURVIVE_THE_IMPORT_GOES_TO_THE_LISTING():
    # A category URL with inbound links is a shopper looking for products. /products is a
    # better answer than a 404 on /category/gone-category.
    Category.objects.create(name="Skin Care", slug="skin-care")

    seed()

    assert Redirect.objects.get(old_path="/product-category/skin-care").new_path == (
        "/category/skin-care"
    )
    assert Redirect.objects.get(old_path="/product-category/gone-category").new_path == (
        "/products"
    )


def test_junk_pages_are_410():
    seed()
    assert Redirect.objects.get(old_path="/home-2-duplicate-5203").status_code == 410


def test_it_is_idempotent():
    seed()
    before = Redirect.objects.count()
    output = seed()
    assert Redirect.objects.count() == before
    assert "Seeded 0 new redirects" in output


def test_a_rerun_corrects_a_target_without_resetting_its_hit_count():
    seed()
    row = Redirect.objects.get(old_path="/our-story")
    Redirect.objects.filter(pk=row.pk).update(new_path="/wrong", hits=42)

    seed()

    row.refresh_from_db()
    assert row.new_path == "/page/our-story"
    # hits measure the OLD url's traffic, which is still true after the target is fixed.
    assert row.hits == 42


def test_dry_run_writes_nothing():
    output = seed("--dry-run")
    assert "DRY RUN" in output
    assert Redirect.objects.count() == 0


# ── the report ───────────────────────────────────────────────────────────────────────────


def test_THE_REPORT_NAMES_REDIRECTS_POINTING_AT_A_PAGE_NOBODY_HAS_WRITTEN():
    """A 301 to a blank page is worse than a 404 — the visitor believes they arrived.
    This is also the outstanding 'eleven pages of policy text' item, surfaced as a list
    instead of a sentence in a plan nobody re-reads."""
    output = seed()

    assert "point at a CMS page that is not published" in output
    assert "/page/our-story" in output


def test_the_report_is_quiet_once_the_page_exists():
    Page.objects.create(title="Our Story", slug="our-story",
                        body_source="<p>x</p>", status=Page.PUBLISHED)
    output = seed()
    assert "/page/our-story" not in output.split("not published")[-1]


def test_THE_DUPLICATE_SLUG_IS_REPORTED_NOT_CRASHED():
    # why-salicylic-acid-works-for-breakouts exists as both a page and a post.
    output = seed()

    assert "duplicate path" in output
    assert "kept the page, dropped the post" in output
    assert Redirect.objects.filter(
        old_path="/why-salicylic-acid-works-for-breakouts"
    ).count() == 1


def test_THE_SHADOWED_ROUTE_IS_REPORTED():
    # /account was a WordPress help article and is the customer's account page here.
    output = seed()
    assert "never fire" in output
    assert "/account" in output


# ── editorial content ────────────────────────────────────────────────────────────────────


def test_content_is_not_imported_without_the_flag():
    seed()
    assert not Page.objects.filter(slug="acne-care-made-easy").exists()


def test_WITH_CONTENT_IMPORTS_THE_BLOG_AS_DRAFT_CMS_PAGES():
    seed("--with-content")

    page = Page.objects.get(slug="acne-care-made-easy")
    assert page.title == "Acne care made easy"
    # DRAFT by default: this is Elementor markup and WordPress shortcodes, and a human
    # should see what survived the allow-list before it is public.
    assert page.status == Page.DRAFT


def test_THE_IMPORTED_BODY_IS_SANITISED_BY_THE_SAME_PATH_AN_AUTHOR_USES():
    # Page.save() runs body_source through cms.sanitize.clean_html. Re-implementing that
    # here would be a second trust boundary that could drift from the first.
    seed("--with-content")

    page = Page.objects.get(slug="acne-care-made-easy")
    assert "<script>" not in page.body
    assert "Wash twice" in page.body
    assert "<script>" in page.body_source  # the submission is kept verbatim


def test_publish_flag_publishes():
    seed("--with-content", "--publish")
    assert Page.objects.get(slug="acne-care-made-easy").status == Page.PUBLISHED


def test_A_POST_WITH_NO_BODY_IS_SKIPPED_not_published_blank():
    output = seed("--with-content")
    assert not Page.objects.filter(slug="empty-post").exists()
    assert "skipped_no_body" in output


def test_A_PAGE_A_HUMAN_HAS_EDITED_IS_NEVER_OVERWRITTEN():
    # Same rule as the customer importer's password handling, for the same reason: a
    # re-run at cutover must not undo work done between the rehearsal and the cutover.
    Page.objects.create(title="Mine", slug="acne-care-made-easy",
                        body_source="<p>I rewrote this.</p>", status=Page.PUBLISHED)

    seed("--with-content")

    page = Page.objects.get(slug="acne-care-made-easy")
    assert page.title == "Mine"
    assert "I rewrote this" in page.body_source
    assert page.status == Page.PUBLISHED


def test_a_missing_artifact_is_a_clean_error(tmp_path):
    with pytest.raises(CommandError, match="No such artifact"):
        call_command("seed_redirects", str(tmp_path / "nope.json"))
