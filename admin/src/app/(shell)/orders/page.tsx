import type { Metadata } from "next";
import { OrderFilterForm } from "@/components/order/OrderFilterForm";
import { OrderStatusTabs } from "@/components/order/OrderStatusTabs";
import { OrderTable } from "@/components/order/OrderTable";
import { Pagination } from "@/components/Pagination";
import { ApiError } from "@/lib/api";
import { ordersQueryString, parseOrderFilters, type OrderPage } from "@/lib/orders";
import { pageCount } from "@/lib/pagination";
import type { CountryRef } from "@/lib/reference";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";

export const metadata: Metadata = { title: "Orders" };

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

const PATH = "/orders";

/** The gateways this store can take money through, for the filter. `payments.gateway` is a
 *  free CharField, so there is no endpoint to ask; these are the five the payments app
 *  implements. Only bank_transfer is live. */
const GATEWAYS = ["bank_transfer", "paystack", "flutterwave", "stripe", "paypal"];

/**
 * `/orders` — the order desk, behind `orders.view`.
 *
 * NOTE THAT LOADING THIS PAGE WRITES AN AUDIT ROW. `AdminOrderListView` is read-audited on
 * purpose: every row carries a customer email and a shipping address, and the `search`
 * parameter is the interesting half — "listed every order matching @gmail.com" is exactly
 * the sentence an audit log exists to be able to write. Paging the queue therefore appears
 * in the log, and that is intended.
 *
 * `fetchWithAuthOrBounce`, never `fetchWithAuth`: a Server Component cannot persist a
 * rotated refresh token, and the writing fetcher would blacklist the old one with nowhere
 * to put the new.
 */
export default async function OrdersPage({ searchParams }: { searchParams: SearchParams }) {
  await requireAdmin(PATH);

  const raw = new URLSearchParams();
  for (const [key, value] of Object.entries(await searchParams)) {
    if (typeof value === "string") raw.set(key, value);
    else if (Array.isArray(value) && value[0] !== undefined) raw.set(key, value[0]);
  }
  const filters = parseOrderFilters(raw);

  const [ordersResult, countriesResult] = await Promise.allSettled([
    (async () => {
      const qs = ordersQueryString(filters);
      return fetchWithAuthOrBounce<OrderPage>(`/admin/orders/${qs ? `?${qs}` : ""}`, PATH);
    })(),
    fetchWithAuthOrBounce<CountryRef[]>("/meta/countries/", PATH),
  ]);

  for (const result of [ordersResult, countriesResult]) {
    // `redirect()` throws; rethrown so a merely-stale session is renewed rather than shown
    // an error page.
    if (result.status === "rejected" && !(result.reason instanceof ApiError)) throw result.reason;
  }

  let error: string | null = null;
  if (ordersResult.status === "rejected") {
    const e = ordersResult.reason as ApiError;
    error =
      e.status === 403
        ? "Your role does not include access to orders."
        : "The orders could not be loaded.";
  }

  const page = ordersResult.status === "fulfilled" ? ordersResult.value : null;
  // A failed country fetch costs the country filter, never the queue.
  const countries =
    countriesResult.status === "fulfilled" && Array.isArray(countriesResult.value)
      ? countriesResult.value.map((c) => ({ code: c.code, name: c.name }))
      : [];

  return (
    <div>
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Orders</h1>
          <p className="mt-1 text-sm text-muted">
            {filters.needs_attention
              ? "Orders where the money did not add up. Every one needs a decision."
              : "The order desk. Search by number, email or address."}
          </p>
        </div>
        {/* Through the BFF proxy, which forwards the admin token and streams the file
            back. A plain link because a download is a navigation, not a fetch. */}
        <a
          href="/api/admin/orders/export.csv"
          className="shrink-0 rounded border border-line px-3 py-1.5 text-sm hover:border-accent"
        >
          Export CSV
        </a>
      </div>

      <div className="mt-6">
        <OrderStatusTabs filters={filters} />
      </div>

      <div className="mt-4">
        <OrderFilterForm filters={filters} countries={countries} gateways={GATEWAYS} />

        {error ? (
          <p className="rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-4 text-sm text-warn">
            {error}
          </p>
        ) : (
          <>
            <p className="mb-2 text-xs text-muted">
              {page?.count ?? 0} {page?.count === 1 ? "order" : "orders"}
            </p>
            <OrderTable rows={page?.results ?? []} />
            <Pagination
              basePath={PATH}
              page={filters.page}
              total={pageCount(page?.count ?? 0)}
              buildQuery={(target) => ordersQueryString({ ...filters, page: target })}
              label="Order pages"
            />
          </>
        )}
      </div>
    </div>
  );
}
