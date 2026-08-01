import type { Metadata } from "next";
import Link from "next/link";
import { Pagination } from "@/components/Pagination";
import { ProductFilterForm } from "@/components/ProductFilterForm";
import { ProductTable } from "@/components/ProductTable";
import { ApiError } from "@/lib/api";
import { pageCount } from "@/lib/pagination";
import { parseProductFilters, productsQueryString, type ProductPage } from "@/lib/products";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";

export const metadata: Metadata = { title: "Products" };

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

const PATH = "/products";

/**
 * The currencies the "Unpriced in" column measures against.
 *
 * Hardcoded, and that is a decision rather than laziness. These are the four seeded by
 * `core/migrations/0003_seed_countries_currencies.py` and they are the four the pricing
 * model is built around; there is no admin endpoint listing configured currencies, and
 * inventing one to avoid four literals would be the larger sin. 17c added
 * `/admin/prices/unpriced/?currency=…`, which answers the per-market question
 * server-side; this list stays hardcoded because it is the set of COLUMNS to show, not a
 * question about any one product.
 */
const CURRENCIES = ["NGN", "GBP", "USD", "CAD"] as const;

/**
 * `/products` — the catalogue list, behind `products.manage`.
 *
 * THE PAGE IS NOT THE AUTHORIZATION. `requireAdmin` establishes a session and nothing
 * more; whether this person may read the catalogue is decided by
 * `HasAdminScope("products.manage")` on the endpoint, on every request, from the database.
 * Somebody without the scope gets a session, a page, and a 403 — rendered as a sentence,
 * because "you may not see this" is an answer and a stack trace is not.
 *
 * `fetchWithAuthOrBounce`, never `fetchWithAuth`: this is a Server Component and cannot
 * persist a rotated refresh token. The writing fetcher would blacklist the old one with
 * nowhere to put the new — a silently ended session. `lib/session.ts` has a dev-time
 * tripwire for exactly this mistake.
 *
 * FILTERS LIVE IN THE URL here, which is the opposite of the editor's tab state (17a
 * design decision 3) and for a reason that does not contradict it: this is a list, not a
 * form. There is nothing unsaved to lose, and a shareable "here is the thing I mean" link
 * is worth having. A form is where navigation destroys work.
 */
export default async function ProductsPage({ searchParams }: { searchParams: SearchParams }) {
  await requireAdmin(PATH);

  const raw = new URLSearchParams();
  for (const [key, value] of Object.entries(await searchParams)) {
    if (typeof value === "string") raw.set(key, value);
    else if (Array.isArray(value) && value[0] !== undefined) raw.set(key, value[0]);
  }
  const filters = parseProductFilters(raw);

  let page: ProductPage | null = null;
  let error: string | null = null;
  try {
    const qs = productsQueryString(filters);
    page = await fetchWithAuthOrBounce<ProductPage>(`/admin/products/${qs ? `?${qs}` : ""}`, PATH);
  } catch (e) {
    // `redirect()` works by THROWING, so a bare catch-all here would swallow the renewal
    // bounce and show an error page to somebody whose session was merely stale.
    if (!(e instanceof ApiError)) throw e;
    error =
      e.status === 403
        ? "Your role does not include managing products."
        : "The product list could not be loaded.";
  }

  const rows = page?.results ?? [];

  return (
    <div>
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Products</h1>
          <p className="mt-1 text-sm text-muted">
            The catalogue. Search by product name or by the SKU printed on the jar.
          </p>
        </div>
        <div className="flex shrink-0 gap-2">
          <Link
            href="/products/unpriced"
            className="rounded border border-line px-3 py-1.5 text-sm hover:border-accent"
          >
            Unpriced
          </Link>
          <Link
            href="/products/new"
            className="rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90"
          >
            New product
          </Link>
        </div>
      </div>

      <div className="mt-6">
        <ProductFilterForm filters={filters} />

        {error ? (
          <p className="rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-4 text-sm text-warn">
            {error}
          </p>
        ) : (
          <>
            <p className="mb-2 text-xs text-muted">
              {page?.count ?? 0} {page?.count === 1 ? "product" : "products"}
            </p>
            <ProductTable rows={rows} currencies={CURRENCIES} />
            <Pagination
              basePath={PATH}
              page={filters.page}
              total={pageCount(page?.count ?? 0)}
              buildQuery={(target) => productsQueryString({ ...filters, page: target })}
              label="Product pages"
            />
          </>
        )}
      </div>
    </div>
  );
}
