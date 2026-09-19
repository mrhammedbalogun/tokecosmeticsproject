import type { Metadata } from "next";
import { cookies } from "next/headers";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";
import { searchProducts, EMPTY_SEARCH_PAGE } from "@/lib/catalog";
import { first, parseSearchParams } from "@/lib/search-params";
import { pageMetadata } from "@/lib/seo";
import { ProductGrid } from "@/components/plp/ProductGrid";
import { ComboCard } from "@/components/combo/ComboCard";

type Search = Promise<Record<string, string | string[] | undefined>>;

export async function generateMetadata({ searchParams }: { searchParams: Search }): Promise<Metadata> {
  const q = (first((await searchParams).q) ?? "").trim();
  return pageMetadata({
    title: q ? `Search: ${q}` : "Search",
    description: "Search the Toke Cosmetics range.",
    path: "/search",
    noindex: true, // thin-content policy; /search is also excluded from the sitemap
  });
}

export default async function SearchPage({ searchParams }: { searchParams: Search }) {
  const raw = await searchParams;
  const params = parseSearchParams(raw);
  const q = params.q ?? "";
  const pageNum = params.page ?? 1;
  const country = (await cookies()).get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;

  // A page beyond the last (crawlers, stale bookmarks, shrunk catalog) DRF-404s —
  // untrusted URL input, so swallow it to the empty state rather than error.
  const page = q
    ? await searchProducts(params, country).catch(() => EMPTY_SEARCH_PAGE)
    : EMPTY_SEARCH_PAGE;

  // Bundles come back on the FIRST PAGE ONLY (they are not paginated) and are absent
  // altogether from an API build that predates combo search — both are `[]` here.
  const combos = page.combos ?? [];
  const nothingAtAll = page.results.length === 0 && combos.length === 0;

  const baseQs = (over: Record<string, string | undefined>) => {
    const qs = new URLSearchParams();
    const merged: Record<string, string | undefined> = {
      q, in_stock: params.in_stock, sort: params.sort, ...over,
    };
    for (const [k, v] of Object.entries(merged)) if (v) qs.set(k, v);
    return `/search?${qs.toString()}`;
  };
  // Prev/Next driven by the API's own next/previous links (no page-size magic number).
  const hasPrev = page.previous !== null;
  const hasNext = page.next !== null;

  return (
    <section className="mx-auto max-w-7xl px-4 py-10">
      <h1 className="font-display text-4xl">
        {q ? <>Results for “{q}”</> : "Search"}
      </h1>
      {q && (
        <form method="GET" action="/search" className="mt-6 flex flex-wrap items-center gap-4 text-sm">
          <input type="hidden" name="q" value={q} />
          <label className="flex items-center gap-2">
            <input type="checkbox" name="in_stock" value="1" defaultChecked={params.in_stock === "1"} />
            In stock only
          </label>
          <label className="text-muted">
            Sort{" "}
            <select name="sort" defaultValue={params.sort ?? ""} className="rounded-md border border-line bg-surface px-2 py-1.5 text-foreground">
              <option value="">Relevance</option>
              <option value="newest">Newest</option>
              <option value="price_asc">Price: low to high</option>
              <option value="price_desc">Price: high to low</option>
            </select>
          </label>
          <button className="rounded-full bg-accent px-5 py-2 font-medium text-surface hover:bg-accent-strong">Apply</button>
          {/* Counted separately, not summed. `count` is the product total ACROSS pages
              while the bundles are the handful on this one, so one number would be
              comparing two different things. */}
          <span className="ml-auto text-muted" aria-live="polite">
            {page.count} {page.count === 1 ? "product" : "products"}
            {combos.length > 0 && (
              <> · {combos.length} {combos.length === 1 ? "bundle" : "bundles"}</>
            )}
          </span>
        </form>
      )}

      {/* BUNDLES FIRST. A combo that matches the words the shopper typed is the better
          answer than the products inside it sold one at a time — and it is the answer
          they could not have searched for, because they did not know the box existed. */}
      {combos.length > 0 && (
        <div className="mt-8">
          <h2 className="font-display text-2xl">Bundles</h2>
          <p className="mt-1 text-sm text-muted">
            Several products in one box, for less than buying them apart.
          </p>
          <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {combos.map((combo, i) => (
              <ComboCard key={combo.slug} combo={combo} priority={i < 3 && page.results.length === 0} />
            ))}
          </div>
        </div>
      )}

      <div className="mt-8">
        {!q ? (
          <p className="text-muted">Type in the search bar above to find products.</p>
        ) : page.results.length > 0 ? (
          <>
            {combos.length > 0 && <h2 className="mb-4 font-display text-2xl">Products</h2>}
            <ProductGrid products={page.results} />
          </>
        ) : nothingAtAll ? (
          // Only when there is genuinely nothing. Bundles matched but no products is a
          // successful search, and "No products to show here." under three bundle cards
          // reads as a failure.
          <ProductGrid products={[]} />
        ) : null}
      </div>

      {(hasPrev || hasNext) && (
        <nav aria-label="Pagination" className="mt-10 flex items-center justify-center gap-2">
          {hasPrev && <a rel="prev" className="rounded-full border border-line px-4 py-2 text-sm hover:border-accent" href={baseQs({ page: pageNum > 2 ? String(pageNum - 1) : undefined })}>← Prev</a>}
          <span className="px-3 text-sm text-muted">Page {pageNum}</span>
          {hasNext && <a rel="next" className="rounded-full border border-line px-4 py-2 text-sm hover:border-accent" href={baseQs({ page: String(pageNum + 1) })}>Next →</a>}
        </nav>
      )}
    </section>
  );
}
