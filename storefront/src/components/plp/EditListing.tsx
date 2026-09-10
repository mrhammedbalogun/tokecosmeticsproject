/**
 * The page body for a "Shop By Edit" listing — Best Sellers, New Arrivals, Promo.
 *
 * ONE COMPONENT FOR ALL THREE. They differ by a title, a sentence and a query param
 * (`shop-edits.ts`); everything else — filters, grid, pager, breadcrumbs, the empty state
 * — is identical, and three near-copies of a PLP is how they stop being identical.
 *
 * The shopper's own filters are read from the URL exactly as they are on `/products`, then
 * the edit's params are layered ON TOP, so `params` wins: `?ordering=price_asc` on
 * /best-sellers cannot quietly turn it into a cheapest-first listing of everything. The
 * sort control is hidden on the two edits where the order IS the page.
 */
import Link from "next/link";
import { fetchPlpPage, getBrands } from "@/lib/catalog";
import type { ShopEdit } from "@/lib/shop-edits";
import { parsePlpParams } from "@/components/plp/plpParams";
import { Breadcrumbs } from "@/components/plp/Breadcrumbs";
import { ProductGrid } from "@/components/plp/ProductGrid";
import { FiltersBar } from "@/components/plp/FiltersBar";
import { Pagination } from "@/components/plp/Pagination";
import { JsonLd } from "@/components/seo/JsonLd";
import { breadcrumbJsonLd } from "@/lib/seo";

type Raw = Record<string, string | string[] | undefined>;

export async function EditListing(
  { edit, searchParams, country }: { edit: ShopEdit; searchParams: Raw; country: string },
) {
  const parsed = parsePlpParams(searchParams);
  // A locked ordering is dropped from the state the CONTROLS see, not just from the
  // fetch. `?ordering=price_asc` on /best-sellers is already ignored when listing (the
  // edit's own params are layered on top); left in `state` it would still ride along in
  // every pager link and the canonical URL, advertising a sort the page does not honour.
  const state = edit.fixedOrdering ? { ...parsed, ordering: undefined } : parsed;
  const base = `/${edit.slug}`;
  const crumbs = [
    { name: "Home", path: "/" },
    { name: edit.title, path: base },
  ];

  const [page, brands] = await Promise.all([
    fetchPlpPage({ ...state, ...edit.params }, country),
    getBrands(country).catch(() => []),
  ]);

  // Has the SHOPPER narrowed this listing? It decides which empty state is honest. An
  // unfiltered Promo page with nothing on it means no promotions are running; the same
  // page filtered to "Brand X under ₦500" means their filter matched nothing, and telling
  // them the shop has no offers — while hiding the filter bar that caused it — leaves
  // them stuck on a page they cannot unstick.
  const filtered = Boolean(
    state.brand || state.price_min || state.price_max || state.page > 1,
  );

  return (
    <section className="mx-auto max-w-7xl px-4 py-8">
      <JsonLd data={breadcrumbJsonLd(crumbs)} />
      <Breadcrumbs crumbs={crumbs} />

      <header className="mt-6 max-w-2xl">
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-accent">
          {edit.kicker}
        </p>
        <h1 className="mt-2 font-display text-3xl leading-tight sm:text-4xl">{edit.title}</h1>
        <p className="mt-3 text-muted">{edit.blurb}</p>
      </header>

      {page.count === 0 && !filtered ? (
        <div className="mt-10 rounded-[var(--radius-card)] border border-dashed border-line bg-surface p-10 text-center">
          <p className="text-muted">{edit.empty}</p>
          <Link
            href="/products"
            className="mt-4 inline-block rounded-full bg-accent px-5 py-2 text-sm font-medium text-surface transition-colors hover:bg-accent-strong"
          >
            Shop all products
          </Link>
        </div>
      ) : (
        <>
          <div className="mt-6">
            <FiltersBar
              base={base}
              state={state}
              brands={brands}
              resultCount={page.count}
              showSort={!edit.fixedOrdering}
            />
          </div>
          <div className="mt-6">
            <ProductGrid products={page.results} />
          </div>
          <Pagination
            base={base}
            state={state}
            hasPrev={page.previous !== null}
            hasNext={page.next !== null}
          />
        </>
      )}
    </section>
  );
}
