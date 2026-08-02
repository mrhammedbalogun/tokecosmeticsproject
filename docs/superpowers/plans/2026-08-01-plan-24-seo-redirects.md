# Plan-24 — SEO and redirects

Master spec: `master-tokerebuild.md` §Plan-24-seo-redirects. Independent of Plan-22/23 —
it needs the catalogue (Plan-21, done), not the customers or orders.

> **Decided 2026-08-01:** the 50 blog and help URLs **ship as CMS pages** — the post bodies
> import into Plan-19's CMS and every one of them redirects to `/page/<slug>`. See
> §Decision. Nothing is blocked.

---

## Grounding (measured on the live host, 2026-08-01)

### What already exists, and does not need building

`storefront/src/app/sitemap.ts` and `robots.ts` are written and sound — the sitemap covers
home, `/products`, CMS pages, categories and every product, with per-page failure isolation
and a runaway guard. Robots disallows `/checkout`, `/account`, `/api/`, `/cart` and points
at the sitemap. **Plan-24 does not touch either.**

`core.Redirect` exists as a model — `old_path`, `new_path`, `status_code`, `hits` — and is
referenced by **nothing**. No middleware, no admin, no seeding, no tests. That is the whole
of this stage.

### The URL space being replaced

WordPress permalinks are `/%postname%/` — **root-level, with a trailing slash**. WooCommerce
bases (from `woocommerce_permalinks`): product `/product`, category `/product-category`,
tag `/product-tag`.

| Old | Count | New |
|---|---|---|
| `/product/<slug>/` | 71 | `/product/<slug>` — **same base, same slug** |
| `/product-category/<slug>/` | 40 | `/category/<slug>` |
| `/product-tag/<slug>/` | 137 | `/products?tag=<slug>` |
| `/<page-slug>/` | 23 | mixed — see below |
| `/<post-slug>/` (blog) | 33 | **decision** |
| `/<help-slug>/` (`motta_help_article`) | 15 | **decision** |

**Product URLs need no redirect rows at all.** Plan-21's importer writes
`"slug": row["slug"]` straight from `post_name` with no slugify (`importers/products.py:74`),
and categories do the same — so the `architecture.md` "byte-identical slugs" guarantee holds
*by construction*, verified in the code rather than assumed. The only difference is the
trailing slash, which Next normalises natively. 71 URLs, zero rows.

Longest product slug is 63 chars against a 170-char `SlugField`, so nothing truncates.

### THE COLLISION THAT DECIDES THE DESIGN

WordPress puts pages, posts and help articles all at the **root**. Three of those slugs are
also real storefront routes:

| Old URL | What it was in WordPress | What it is now |
|---|---|---|
| `/account/` | a `motta_help_article` | **the customer's account page** |
| `/search/` | a page | **the search page** |
| `/checkout/` | a page | the checkout page |

A redirect layer that consulted the table *before* routing would send a signed-in customer
from their own account page to a help article about accounts. That is not a hypothetical
ordering worry — those rows exist today.

### Other measured facts that shape the work

- **`why-salicylic-acid-works-for-breakouts` exists as BOTH a page and a post.** `old_path`
  is `unique`, so a naive seeder raises `IntegrityError` — or, worse, silently keeps
  whichever row it processed last.
- **No redirect plugin to inherit.** The only SEO plugin tables (`aioseo_*`) are on the
  **NG-old** prefix, not the live store. There is no existing redirect map to preserve, and
  nothing to merge.
- **Junk pages that should not be redirected anywhere**: `home-2-duplicate-5203`,
  `wishsuite`, `search-results`, `check-out` (a duplicate of `checkout`), `affiliates-2`,
  `shop-page`.
- **Two "pages" are really articles**: `this-valentine-love-their-skin-the-toke-way` and
  `why-salicylic-acid-works-for-breakouts`. They belong with the blog decision, not with
  the policy pages.
- **Category slugs carry WordPress's history**: `skin-care` *and* `skin-care-2`, `promo`
  and `promo-2`, `hair-care` and `hair-care-shop-by-category`, plus `uncategorized`,
  `shop-all` and a category literally slugged `products`. Redirects point at whatever
  Plan-21 actually created; a category that did not survive the import redirects to
  `/products` rather than to a 404.

---

## Design rulings

### 1. Redirects are a 404 FALLBACK, and the framework enforces it

Not middleware. A root catch-all route — `storefront/src/app/[...slug]/page.tsx` — which
Next reaches **only when no real route matched**, because the App Router already ranks
static and dynamic segments above catch-alls.

That is the entire reason to do it this way. The alternative — middleware that looks up
every incoming path — needs a hand-maintained list of paths to skip, and the day somebody
forgets to add a new route to that list is the day it starts redirecting a real page. Here
the precedence is a property of the router, not of a list I have to keep correct. `/account`
resolves to the account page and the redirect table is never consulted.

Consequence to accept: the lookup happens on a request that was going to be a 404 anyway,
so its cost is bounded by 404 traffic, and the result is cached.

### 2. Trailing slashes are normalised at seed time, matched at lookup

Every old URL ends in `/`; no new one does. `old_path` is stored **without** the trailing
slash, and the lookup strips it before matching, so `/our-story/` and `/our-story` both
resolve. Storing both forms would double the table and give two rows that can disagree.

### 3. Seeding is deterministic, and a duplicate slug is a report line, not a crash

`seed_redirects` takes the same extract-artifact shape as the rest of the migration. When
two source rows claim one `old_path` — which happens once today, and will happen again the
next time somebody publishes a post with a page's slug — precedence is **page > post >
help article**, applied by sorting, so a re-run reaches the same answer. The loser is
counted and listed in the report rather than silently dropped or allowed to raise.

### 4. Functional pages redirect to the feature, not to `/page/<slug>`

`my-account` → `/account`, `shop-page` → `/products`, `checkout` → `/checkout`,
`search` → `/search`, `home` → `/`. Sending `/my-account/` to a CMS page that says
"My Account" would be technically a redirect and practically a dead end.

The genuinely editorial ones — `our-story`, `careers`, `help`, `returns-exchanges`,
`terms-conditions`, `become-a-distributor`, `our-stores`, `gifts`, `entrepreneur`,
`affiliate-terms-and-conditions` — go to `/page/<slug>`, which is where Plan-19's CMS
serves them. **Those pages still need their copy** — that is the outstanding "eleven pages
of policy text" item, and this plan does not resolve it: a redirect to an empty page is a
worse experience than a 404, so the seeder marks any target with no published CMS page and
lists it.

### 5. Junk 410s rather than redirecting

`home-2-duplicate-5203` and friends have no successor. A 301 to the homepage tells Google
the content moved there, which is false and dilutes the homepage. `410 Gone` is the honest
answer and gets them de-indexed faster. `Redirect.status_code` already supports it.

### 6. `hits` is best-effort and never blocks the redirect

The counter is for finding which old URLs still get traffic — useful for a year, then
noise. It must never turn a redirect into a failed request: the increment is a fire-and-
forget `F()`-expression update, and an exception in it is logged and swallowed. A redirect
that 500s because a counter failed is strictly worse than one that under-counts.

---

## Tasks

1. **`Redirect` admin + API** — list/create/edit/delete under `cms.manage`, with the four
   guard declarations every admin endpoint needs (surface, role matrix, audit write cases,
   read-audited views).
2. **Lookup endpoint** — `GET /api/v1/redirects/resolve/?path=`, cached, returning
   `{new_path, status_code}` or 404.
3. **`storefront/src/app/[...slug]/page.tsx`** — resolve, then `permanentRedirect()` /
   `redirect()` / `notFound()`.
4. **`seed_redirects`** management command — from a WP extract, idempotent, with the
   precedence rule and a counts-only report.
5. **Extract the URL space** — extend the catalogue extractor, or a small
   `extract_wp_urls`, for pages/posts/terms.
6. **Tests**: the `/account` collision, the duplicate-slug precedence, trailing slashes,
   410s, and that no seeded `old_path` shadows a real storefront route.

---

## Decision needed — 50 blog and help URLs

The new platform has **no blog**. WordPress has:

- **33 published posts**, most recent **31 July 2026 — yesterday**. This is not a dormant
  archive; it is actively published to.
- **15 `motta_help_article` entries** (a theme post type) behind `/help`.
- **2 pages that are really articles** (the Valentine's and salicylic-acid ones).

They are real content with real inbound links. Three options, and this is a content
decision rather than a technical one:

- **Ship them as CMS pages.** Plan-19's CMS already serves `/page/<slug>` with sanitised
  HTML. 50 redirects to 50 real pages, nothing lost. Costs a migration pass to import the
  post bodies, and `/page/blog` becomes an index somebody has to maintain by hand.
- **Redirect them to the closest product or category.** Cheap, and about half of these
  posts are really product announcements (`toke-carrot-shea-butter`,
  `toke-men-essentials`). Loses the editorial content, and Google treats a redirect to a
  non-equivalent page as a soft 404.
- **410 them.** Honest, fastest to implement, and throws away a year of content and
  whatever SEO it earned.

**DECIDED: ship them as CMS pages.** The blog is live — something published yesterday must
not 404 on cutover day.

This adds a seventh task: an editorial import pass that reads `post_content` for the 33
posts, 15 help articles and 2 article-pages, sanitises it through `apps.cms.sanitize`
(nh3 — the same path Plan-19's CMS already runs its bodies through, so no new trust
boundary) and writes `cms.Page` rows. The redirects then point at pages that actually
exist, which is the thing ruling 4 insists on.

`/page/blog` becomes a hand-maintained index. That is a real ongoing cost and it is
accepted knowingly: the alternative is building a blog engine inside a migration stage.
