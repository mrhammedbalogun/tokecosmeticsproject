import type { Metadata } from "next";
import Link from "next/link";
import { Pagination } from "@/components/Pagination";
import { ApiError } from "@/lib/api";
import { pageCount } from "@/lib/pagination";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";

export const metadata: Metadata = { title: "Unpriced" };

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

const PATH = "/products/unpriced";

/** The configured currencies, as on the products list — the four seeded by
 *  `core/migrations/0003_seed_countries_currencies.py`. There is no endpoint listing them. */
const CURRENCIES = ["NGN", "GBP", "USD", "CAD"] as const;

interface UnpricedRow {
  variant_id: number;
  sku: string;
  variant_name: string;
  product_name: string;
  product_slug: string;
}

/**
 * `/products/unpriced` — what is not sellable in a given market yet. Plan-17c Task 7.
 *
 * THE OTHER DIRECTION FROM THE PRODUCTS LIST. That list answers "what is this product
 * missing?", one row at a time. This answers the question somebody actually has on the day
 * a market opens: "what is not sellable HERE yet?" — which is a list to work through and
 * finish, not a column to scan.
 *
 * It matters because a market needs a price in its own currency before the product appears
 * in it at all, and every one of the 121 production prices is NGN. A glance at "has a
 * price" would call the whole catalogue ready for the UK.
 *
 * ACTIVE PRODUCTS ONLY, decided server-side: a draft with no GBP price is not a gap in the
 * catalogue, and listing it would pad a checklist that exists to reach zero.
 */
export default async function UnpricedPage({ searchParams }: { searchParams: SearchParams }) {
  await requireAdmin(PATH);

  const params = await searchParams;
  const raw = typeof params.currency === "string" ? params.currency.toUpperCase() : "";
  const currency = (CURRENCIES as readonly string[]).includes(raw) ? raw : CURRENCIES[0];
  const pageParam = Number(typeof params.page === "string" ? params.page : "1");
  const page = Number.isFinite(pageParam) && pageParam >= 1 ? Math.floor(pageParam) : 1;

  let data: { count: number; results: UnpricedRow[] } | null = null;
  let error: string | null = null;
  try {
    const qs = new URLSearchParams({ currency });
    if (page > 1) qs.set("page", String(page));
    data = await fetchWithAuthOrBounce(`/admin/prices/unpriced/?${qs.toString()}`, PATH);
  } catch (e) {
    // `redirect()` throws; rethrown so a merely-stale session is renewed.
    if (!(e instanceof ApiError)) throw e;
    error =
      e.status === 403
        ? "Your role does not include managing prices."
        : "The list could not be loaded.";
  }

  const rows = data?.results ?? [];

  return (
    <div>
      <div>
        <Link href="/products" className="text-sm text-muted hover:text-foreground">
          ← Products
        </Link>
        <h1 className="mt-2 text-lg font-semibold tracking-tight">Unpriced in a market</h1>
        <p className="mt-1 text-sm text-muted">
          A product needs a price in a market&rsquo;s currency before it appears there at
          all. These active variants have none.
        </p>
      </div>

      <nav className="mt-6 flex flex-wrap gap-2" aria-label="Currency">
        {CURRENCIES.map((code) => (
          <Link
            key={code}
            href={`${PATH}?currency=${code}`}
            aria-current={code === currency ? "page" : undefined}
            className={`rounded-full border px-3 py-1 text-sm ${
              code === currency ? "border-accent text-accent" : "border-line text-muted"
            }`}
          >
            {code}
          </Link>
        ))}
      </nav>

      <div className="mt-4">
        {error ? (
          <p className="rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-4 text-sm text-warn">
            {error}
          </p>
        ) : rows.length === 0 && page === 1 ? (
          <p className="rounded-[var(--radius-card)] border border-ok/40 bg-ok/5 p-6 text-center text-sm text-ok">
            Every active variant has a {currency} price.
          </p>
        ) : (
          <>
            <p className="mb-2 text-xs text-muted">
              {data?.count ?? 0} {data?.count === 1 ? "variant" : "variants"} with no{" "}
              {currency} price
            </p>
            <div className="overflow-hidden rounded-[var(--radius-card)] border border-line">
              <table className="w-full text-sm">
                <thead className="bg-surface text-xs uppercase tracking-wide text-muted">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium">Product</th>
                    <th className="px-3 py-2 text-left font-medium">SKU</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.variant_id} className="border-t border-line">
                      <td className="px-3 py-2">
                        {/* Straight to the Prices tab, because that is the next action. */}
                        <Link
                          href={`/products/${row.product_slug}`}
                          className="underline underline-offset-2 hover:text-accent"
                        >
                          {row.product_name}
                        </Link>
                        {row.variant_name && (
                          <span className="text-muted"> · {row.variant_name}</span>
                        )}
                      </td>
                      <td className="px-3 py-2 font-mono text-xs">{row.sku}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination
              basePath={PATH}
              page={page}
              total={pageCount(data?.count ?? 0)}
              buildQuery={(target) =>
                target > 1 ? `currency=${currency}&page=${target}` : `currency=${currency}`
              }
              label="Unpriced pages"
            />
          </>
        )}
      </div>
    </div>
  );
}
