"""The legacy→new URL map. Cases are the live site's real slugs, measured 2026-08-01."""

import pytest

from apps.migration_wp.transform_urls import (
    CATEGORY_FALLBACK,
    GONE_PAGES,
    STOREFRONT_ROUTES,
    build_redirects,
    page_target,
    shadowed_routes,
)


def artifact(**kw):
    base = {"pages": [], "posts": [], "helps": [], "categories": [], "tags": []}
    base.update(kw)
    return base


def by_path(rows):
    return {r["old_path"]: r for r in rows}


# ── the collision that decides the design ────────────────────────────────────────────────


def test_A_HELP_ARTICLE_AT_slash_account_IS_FLAGGED_AS_SHADOWED():
    """WordPress served a help article at /account/. The storefront serves the customer's
    ACCOUNT PAGE there. The row can never fire — the App Router ranks the real route above
    the catch-all — but a row that looks like it works and never does is how somebody
    loses an afternoon."""
    rows, _ = build_redirects(artifact(helps=[{"slug": "account"}]))

    assert shadowed_routes(rows) == ["/account"]


def test_the_functional_page_slugs_that_collide_do_not_shadow_because_they_are_remapped():
    # /search and /checkout were WordPress pages AND are storefront routes. They map to
    # the feature, so their old_path is still /search — also shadowed, and correctly so:
    # the storefront already serves that URL, which is the outcome we wanted anyway.
    rows, _ = build_redirects(artifact(pages=[{"slug": "search"}, {"slug": "checkout"}]))
    paths = by_path(rows)

    assert paths["/search"]["new_path"] == "/search"
    assert paths["/checkout"]["new_path"] == "/checkout"


def test_no_seeded_row_outside_the_root_namespace_shadows_a_route():
    # Categories, tags and products live under their own bases, so they can never collide
    # with a top-level route however WordPress slugged them — including the category
    # literally slugged "products".
    rows, _ = build_redirects(
        artifact(categories=[{"slug": "products"}], tags=[{"slug": "account"}])
    )
    assert shadowed_routes(rows) == []


# ── the duplicate slug ───────────────────────────────────────────────────────────────────


def test_THE_PAGE_AND_POST_SHARING_A_SLUG_DO_NOT_CRASH_THE_SEEDER():
    """`why-salicylic-acid-works-for-breakouts` exists today as BOTH a page and a post.
    `Redirect.old_path` is unique, so this either raises or silently keeps whichever row
    was processed last — and which one that is could differ between the rehearsal and the
    cutover."""
    slug = "why-salicylic-acid-works-for-breakouts"
    rows, conflicts = build_redirects(
        artifact(pages=[{"slug": slug}], posts=[{"slug": slug}])
    )

    assert len(rows) == 1
    assert len(conflicts) == 1
    assert conflicts[0]["kept"] == "page" and conflicts[0]["dropped"] == "post"


def test_the_winner_does_not_depend_on_input_order():
    slug = "why-salicylic-acid-works-for-breakouts"
    a, _ = build_redirects(artifact(pages=[{"slug": slug}], posts=[{"slug": slug}]))
    b, _ = build_redirects(artifact(posts=[{"slug": slug}], pages=[{"slug": slug}]))
    assert a == b


def test_a_conflict_is_reported_rather_than_dropped_silently():
    slug = "dup"
    _, conflicts = build_redirects(
        artifact(pages=[{"slug": slug}], posts=[{"slug": slug}], helps=[{"slug": slug}])
    )
    assert len(conflicts) == 2  # both losers named


# ── the mappings ─────────────────────────────────────────────────────────────────────────


def test_editorial_pages_go_to_the_cms():
    rows, _ = build_redirects(artifact(pages=[{"slug": "our-story"}]))
    assert by_path(rows)["/our-story"]["new_path"] == "/page/our-story"


@pytest.mark.parametrize(
    "slug,target",
    [("my-account", "/account"), ("shop-page", "/products"), ("home", "/"),
     ("search-results", "/search"), ("check-out", "/checkout")],
)
def test_FUNCTIONAL_PAGES_GO_TO_THE_FEATURE_NOT_TO_AN_ARTICLE_ABOUT_IT(slug, target):
    # /my-account/ -> a CMS page titled "My Account" would be technically a redirect and
    # practically a dead end.
    assert page_target(slug) == (target, 301)


def test_junk_pages_are_410_GONE_not_301_to_the_homepage():
    # A 301 to the homepage tells Google the content MOVED there. It did not — it was
    # abandoned — and the claim dilutes the homepage's own relevance.
    for slug in GONE_PAGES:
        new, status = page_target(slug)
        assert status == 410 and new == ""


def test_the_gone_list_is_short_on_purpose():
    # When in doubt a page is editorial: a redirect is recoverable, a 410 is not.
    assert len(GONE_PAGES) <= 3


def test_BLOG_POSTS_AND_HELP_ARTICLES_BECOME_CMS_PAGES():
    # Decided 2026-08-01. The blog was published to the day before this was written; a
    # post from yesterday must not 404 on cutover day.
    rows, _ = build_redirects(
        artifact(posts=[{"slug": "acne-care-made-easy"}],
                 helps=[{"slug": "help-with-password"}])
    )
    paths = by_path(rows)
    assert paths["/acne-care-made-easy"]["new_path"] == "/page/acne-care-made-easy"
    assert paths["/help-with-password"]["new_path"] == "/page/help-with-password"


def test_categories_move_base():
    rows, _ = build_redirects(artifact(categories=[{"slug": "skin-care-2"}]))
    assert by_path(rows)["/product-category/skin-care-2"]["new_path"] == "/category/skin-care-2"


def test_TAGS_KEEP_THE_SHOPPERS_INTENT_even_though_there_is_no_tag_route():
    # 137 of these. The PLP already supports ?tag=, so the filter survives the move.
    rows, _ = build_redirects(artifact(tags=[{"slug": "shea-butter"}]))
    row = by_path(rows)["/product-tag/shea-butter"]
    assert row["new_path"] == f"{CATEGORY_FALLBACK}?tag=shea-butter"


def test_NO_ROWS_ARE_EMITTED_FOR_PRODUCTS():
    """Plan-21 preserves post_name verbatim and the base is /product on both sides, so
    every product row would say "this URL redirects to itself" — 71 chances for one of
    them to be wrong, buying nothing. The trailing slash is Next's job."""
    rows, _ = build_redirects(artifact(pages=[], posts=[]))
    assert rows == []


# ── shape ────────────────────────────────────────────────────────────────────────────────


def test_every_old_path_is_normalised():
    from apps.core.redirects import normalise_path

    rows, _ = build_redirects(
        artifact(pages=[{"slug": "Our-Story"}], categories=[{"slug": "Skin-Care"}])
    )
    for row in rows:
        assert row["old_path"] == normalise_path(row["old_path"])


def test_blank_slugs_are_skipped_not_turned_into_a_root_redirect():
    # A row with an empty slug would become old_path="/" — a redirect off the homepage.
    rows, _ = build_redirects(artifact(pages=[{"slug": ""}, {"slug": None}, {}]))
    assert rows == []


def test_the_storefront_route_list_covers_every_real_top_level_route():
    # If a route is added to the storefront and not here, shadowed_routes stops detecting
    # collisions with it. Cheap tripwire for a change made in another repo directory.
    for route in ("/account", "/cart", "/category", "/checkout", "/orders", "/page",
                  "/product", "/products", "/search", "/login", "/register"):
        assert route in STOREFRONT_ROUTES
