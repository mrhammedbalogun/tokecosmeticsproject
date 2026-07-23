import type { Metadata } from "next";
import { cookies } from "next/headers";
import { ApiError } from "@/lib/api";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";
import { getBrands, getProducts, type Paginated, type ProductCard } from "@/lib/catalog";
import { pageMetadata } from "@/lib/seo";
import { parsePlpParams } from "@/components/plp/plpParams";
import { ProductGrid } from "@/components/plp/ProductGrid";
import { FiltersBar } from "@/components/plp/FiltersBar";
import { Pagination } from "@/components/plp/Pagination";

type Search = Promise<Record<string, string | string[] | undefined>>;

export async function generateMetadata({ searchParams }: { searchParams: Search }): Promise<Metadata> {
  const raw = await searchParams;
  return pageMetadata({
    title: "Shop All Products",
    description: "Browse the full Toke Cosmetics range — face, body, hair and family skincare made for melanin-rich skin.",
    path: "/products",
    searchParams: Object.fromEntries(
      Object.entries(raw).map(([k, v]) => [k, Array.isArray(v) ? v[0] : v]),
    ),
  });
}

const EMPTY_PAGE: Paginated<ProductCard> = { count: 0, next: null, previous: null, results: [] };

/** A `page` beyond the last one makes DRF pagination 404. That is untrusted URL
 * input (crawlers, stale bookmarks, a shrunk catalog), not a server fault — treat
 * it as "no results" and render the empty state. Any other error still bubbles. */
async function fetchProducts(state: ReturnType<typeof parsePlpParams>, country: string) {
  try {
    return await getProducts(state, country);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return EMPTY_PAGE;
    throw err;
  }
}

export default async function ProductsPage({ searchParams }: { searchParams: Search }) {
  const state = parsePlpParams(await searchParams);
  const country = (await cookies()).get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  const [page, brands] = await Promise.all([
    fetchProducts(state, country),
    getBrands(country).catch(() => []),
  ]);
  return (
    <section className="mx-auto max-w-7xl px-4 py-10">
      <h1 className="font-display text-4xl">All products</h1>
      <div className="mt-6">
        <FiltersBar base="/products" state={state} brands={brands} resultCount={page.count} />
      </div>
      <div className="mt-6">
        <ProductGrid products={page.results} />
      </div>
      <Pagination base="/products" state={state}
        hasPrev={page.previous !== null} hasNext={page.next !== null} />
    </section>
  );
}
