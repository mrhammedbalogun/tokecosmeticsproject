import type { Metadata } from "next";
import { Pagination } from "@/components/Pagination";
import { StoreDirectory } from "@/components/stores/StoreDirectory";
import { StoreFilterForm } from "@/components/stores/StoreFilterForm";
import { ApiError } from "@/lib/api";
import { pageCount } from "@/lib/pagination";
import type { CountryRef } from "@/lib/reference";
import type { RegionRow } from "@/lib/regions";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";
import { parseStoreFilters, storesQueryString, type StorePage } from "@/lib/stores";

export const metadata: Metadata = { title: "Find a Store" };

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

const PATH = "/find-stores";

/**
 * `/find-stores` — the store directory behind the customer-facing locator, scoped
 * `products.manage` (Owner and Manager).
 *
 * THE PAGE IS NOT THE AUTHORIZATION. `requireAdmin` establishes a session and nothing
 * more; whether this person may manage stores is decided by
 * `HasAdminScope("products.manage")` on every endpoint, on every request, from the
 * database. Somebody without the scope gets a session, a page, and a 403 — rendered as
 * a sentence, because "you may not see this" is an answer and a stack trace is not.
 *
 * `fetchWithAuthOrBounce`, never `fetchWithAuth`: this is a Server Component and cannot
 * persist a rotated refresh token.
 *
 * ── WHY THE WHOLE REGION TREE RIDES ALONG ───────────────────────────────────────────
 *
 * `/admin/regions/` is 811 rows for Nigeria alone, unpaginated, and both the filter bar
 * and the add/edit form need the same cascade. Sending it once and filtering in the
 * browser costs one request; the alternative is a fetch per dropdown change, on a page
 * whose entire job is picking places. The customer-facing page does the OPPOSITE and is
 * right to — it asks the API for only the places that hold a store, because a customer
 * must never be offered an LGA that will answer "nothing here", while an operator
 * filing a new shop must be able to pick an LGA that holds nothing yet.
 */
export default async function FindStoresPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  await requireAdmin(PATH);

  const raw = new URLSearchParams();
  for (const [key, value] of Object.entries(await searchParams)) {
    if (typeof value === "string") raw.set(key, value);
    else if (Array.isArray(value) && value[0] !== undefined) raw.set(key, value[0]);
  }
  const filters = parseStoreFilters(raw);

  let page: StorePage | null = null;
  let countries: CountryRef[] = [];
  let regions: RegionRow[] = [];
  let error: string | null = null;
  try {
    const qs = storesQueryString(filters);
    const [stores, countryList, regionList] = await Promise.all([
      fetchWithAuthOrBounce<StorePage>(`/admin/stores/${qs ? `?${qs}` : ""}`, PATH),
      // Reference data degrades rather than failing the page: a missing country list
      // costs the operator a filter, a thrown one costs them the directory.
      fetchWithAuthOrBounce<CountryRef[]>("/meta/countries/", PATH).catch(() => []),
      fetchWithAuthOrBounce<RegionRow[]>("/admin/regions/", PATH).catch(() => []),
    ]);
    page = stores;
    countries = (Array.isArray(countryList) ? countryList : [])
      // "ZZ / International" is a pricing bucket, not a place with shops in it — the
      // serializer's own queryset excludes it, so offering it here would only produce
      // a 400.
      .filter((c) => !c.is_rest_of_world)
      .sort((a, b) => a.name.localeCompare(b.name));
    regions = Array.isArray(regionList) ? regionList : [];
  } catch (e) {
    // `redirect()` works by THROWING, so a bare catch-all here would swallow the
    // renewal bounce and show an error page to somebody whose session was merely stale.
    if (!(e instanceof ApiError)) throw e;
    error =
      e.status === 403
        ? "Your role does not include managing stores."
        : "The store directory could not be loaded.";
  }

  const rows = page?.results ?? [];

  return (
    <div>
      <h1 className="text-lg font-semibold tracking-tight">Find a Store</h1>
      <p className="mt-1 text-sm text-muted">
        Every shop a customer can walk into — our own counters and the distributors who
        stock us. Active stores appear on{" "}
        <span className="font-medium">tokecosmetics.com/find-stores</span>; hidden and
        archived ones stay here.
      </p>

      <div className="mt-6">
        {error ? (
          <p className="rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-4 text-sm text-warn">
            {error}
          </p>
        ) : (
          <>
            <StoreFilterForm filters={filters} countries={countries} regions={regions} />
            <p className="mb-2 text-xs text-muted">
              {page?.count ?? 0} {page?.count === 1 ? "store" : "stores"} match.
            </p>
            <StoreDirectory rows={rows} countries={countries} regions={regions} />
            <Pagination
              basePath={PATH}
              page={filters.page}
              total={pageCount(page?.count ?? 0)}
              buildQuery={(target) => storesQueryString({ ...filters, page: target })}
              label="Store pages"
            />
          </>
        )}
      </div>
    </div>
  );
}
