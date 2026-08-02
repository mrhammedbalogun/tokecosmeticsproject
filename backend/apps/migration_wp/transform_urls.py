"""Build the legacy→new URL map (Plan-24). Pure functions, no database.

Every rule here was derived from the live site's actual URL space, measured 2026-08-01,
not from what a WooCommerce install usually looks like.
"""

from __future__ import annotations

from apps.core.redirects import normalise_path

#: Old root-level pages that are FEATURES on the new platform, not content.
#:
#: Sending `/my-account/` to a CMS page titled "My Account" would be technically a
#: redirect and practically a dead end — the visitor wanted their account, not an article
#: about accounts. These go to the feature.
FUNCTIONAL_PAGES = {
    "my-account": "/account",
    "shop-page": "/products",
    "checkout": "/checkout",
    "check-out": "/checkout",     # a real duplicate page in WordPress
    "search": "/search",
    "search-results": "/search",
    "home": "/",
}

#: Pages with no successor, which get 410 Gone rather than a redirect.
#:
#: A 301 to the homepage tells Google the content MOVED there. It did not — it was
#: abandoned — and the claim dilutes the homepage's own relevance. 410 is the honest
#: answer and de-indexes faster. Kept deliberately short: when in doubt a page is
#: editorial, because a redirect is recoverable and a 410 is not.
GONE_PAGES = {
    "home-2-duplicate-5203",   # a duplicated homepage draft that got published
    "wishsuite",               # a plugin's own page
}

#: Where an unresolvable category points. Not a 404: a category URL with inbound links is
#: a shopper looking for products, and the full listing is a better answer than nothing.
CATEGORY_FALLBACK = "/products"

#: Precedence when two WordPress rows claim the same root path. WordPress itself resolves
#: this ambiguity in favour of pages, and `why-salicylic-acid-works-for-breakouts` exists
#: today as BOTH a page and a post. Lower sorts first and wins.
SOURCE_RANK = {"page": 0, "post": 1, "help": 2}


def page_target(slug: str) -> tuple[str, int]:
    """(new_path, status_code) for a root-level WordPress page."""
    if slug in GONE_PAGES:
        return "", 410
    if slug in FUNCTIONAL_PAGES:
        return FUNCTIONAL_PAGES[slug], 301
    return f"/page/{slug}", 301


def build_redirects(data: dict) -> tuple[list[dict], list[dict]]:
    """(rows, conflicts). Deterministic: same artifact in, same rows out.

    NOTHING IS EMITTED FOR PRODUCTS. Plan-21 preserves `post_name` verbatim as the slug
    and the base is `/product` on both sides, so the only difference is WordPress's
    trailing slash — which Next normalises natively. 71 rows that would all say "this URL
    redirects to itself" is 71 chances for one of them to be wrong.

    Conflicts are RETURNED, not raised and not silently dropped. `Redirect.old_path` is
    unique, so a duplicate would otherwise either kill the run or leave whichever row
    happened to be processed last — and which one that is could change between the
    rehearsal and the cutover.
    """
    candidates: list[tuple[int, str, dict]] = []

    for kind in ("page", "post", "help"):
        for row in data.get(f"{kind}s", []):
            slug = (row.get("slug") or "").strip()
            if not slug:
                continue
            old = normalise_path(f"/{slug}")
            if kind == "page":
                new, status = page_target(slug)
            else:
                # Posts and help articles become CMS pages (decided 2026-08-01). The blog
                # is live — something published the day before cutover must not 404.
                new, status = f"/page/{slug}", 301
            candidates.append(
                (SOURCE_RANK[kind], old, {"old_path": old, "new_path": new,
                                          "status_code": status, "source": kind})
            )

    for term in data.get("categories", []):
        slug = (term.get("slug") or "").strip()
        if not slug:
            continue
        old = normalise_path(f"/product-category/{slug}")
        candidates.append((0, old, {
            "old_path": old,
            # Pointed at the category that Plan-21 actually created; the seeder downgrades
            # this to CATEGORY_FALLBACK when the slug did not survive the import.
            "new_path": f"/category/{slug}",
            "status_code": 301,
            "source": "category",
        }))

    for term in data.get("tags", []):
        slug = (term.get("slug") or "").strip()
        if not slug:
            continue
        old = normalise_path(f"/product-tag/{slug}")
        candidates.append((0, old, {
            "old_path": old,
            # The PLP already supports ?tag=, so the shopper's intent survives the move
            # even though there is no dedicated tag route.
            "new_path": f"{CATEGORY_FALLBACK}?tag={slug}",
            "status_code": 301,
            "source": "tag",
        }))

    # Sort by (path, rank) so the winner of a collision is decided by SOURCE_RANK and
    # never by input order — the rehearsal and the cutover must agree.
    candidates.sort(key=lambda c: (c[1], c[0]))

    rows: list[dict] = []
    conflicts: list[dict] = []
    seen: dict[str, dict] = {}
    for _rank, old, row in candidates:
        if old in seen:
            conflicts.append({"old_path": old, "kept": seen[old]["source"],
                              "dropped": row["source"], "dropped_target": row["new_path"]})
            continue
        seen[old] = row
        rows.append(row)
    return rows, conflicts


#: Storefront routes a redirect must never claim. If a seeded `old_path` matched one of
#: these, the catch-all would never be reached for it anyway (the App Router ranks real
#: routes higher) — so the row would be dead weight that LOOKS like it works. Asserted in
#: the tests so the table cannot quietly fill with rows nobody can trigger.
STOREFRONT_ROUTES = frozenset(
    {
        "/", "/account", "/cart", "/category", "/checkout", "/forgot-password",
        "/login", "/orders", "/page", "/product", "/products", "/register",
        "/reset-password", "/search", "/verify-email",
    }
)


def shadowed_routes(rows: list[dict]) -> list[str]:
    """Old paths that a real storefront route already owns. See STOREFRONT_ROUTES.

    `/account` is the live example: WordPress served a help article there and the
    storefront serves the customer's account page. The row is harmless — it can never
    fire — but it is a lie in the table, and somebody debugging a redirect later would
    waste an afternoon on it.
    """
    return sorted(r["old_path"] for r in rows if r["old_path"] in STOREFRONT_ROUTES)
