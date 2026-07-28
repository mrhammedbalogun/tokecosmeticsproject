import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ApiError } from "@/lib/api";
import { first } from "@/lib/search-params";
import { formatOrderDate, getOrders, type OrderListItem, type Paginated } from "@/lib/orders";
import { StatusChip } from "@/components/orders/StatusChip";
import { Pagination } from "@/components/ui/Pagination";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

// The account layout already sets robots noindex for everything beneath it.
export const metadata: Metadata = { title: "My orders" };

/** Untrusted URL input → a page number DRF will accept. Anything that is not a positive
 * integer (0, -1, 1.5, "abc") falls back to the first page rather than being forwarded
 * verbatim — same discipline as parsePlpParams. `first()` collapses a repeated param
 * before the check, so `?page=2&page=9` is page 2 rather than the array "2,9".
 *
 * isSafeInteger, not isInteger: 1e21 IS an integer to isInteger, and would reach the
 * query string in exponent form. */
function parsePage(raw: string | string[] | undefined): number {
  const page = Number(first(raw));
  return Number.isSafeInteger(page) && page > 0 ? page : 1;
}

async function loadOrders(page: number, currentPath: string): Promise<Paginated<OrderListItem>> {
  try {
    return await getOrders(page, currentPath);
  } catch (e) {
    // DRF 404s a page past the last one ("Invalid page"), which is a bad URL, not an error.
    if (e instanceof ApiError && e.status === 404) notFound();
    // Anything else — including the NEXT_REDIRECT that getOrders throws to renew a stale
    // session — must propagate untouched.
    throw e;
  }
}

export default async function OrdersPage({ searchParams }: { searchParams: SearchParams }) {
  const page = parsePage((await searchParams).page);
  // The bounce target must be this exact URL, page included, or a renewal mid-history
  // dumps the customer back on page 1.
  //
  // It only pays off on SOFT navigation. On a hard load the account layout renders first
  // and its own /auth/me/ fetch bounces with a hardcoded "/account", so a stale token
  // lands the customer on the dashboard whatever we put here. Precision still belongs
  // here: soft navigation does not re-run the layout, so this value is the only one.
  const currentPath = page === 1 ? "/account/orders" : `/account/orders?page=${page}`;
  const orders = await loadOrders(page, currentPath);

  return (
    <div>
      <h2 className="font-display text-2xl">Orders</h2>

      {orders.count === 0 ? (
        <p className="mt-6 text-sm text-muted">
          You haven&rsquo;t placed an order yet.{" "}
          <Link href="/products" className="text-accent-strong underline underline-offset-2">
            Browse products
          </Link>
        </p>
      ) : (
        <ul className="mt-6 space-y-3">
          {orders.results.map((order) => (
            <li key={order.number}>
              <Link
                // Encoded: migrated legacy numbers are not guaranteed to be URL-safe, and
                // an unencoded "#" or "?" would silently truncate the path.
                href={`/account/orders/${encodeURIComponent(order.number)}`}
                className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 rounded-[var(--radius-card)] border border-line p-4 transition-colors hover:bg-beige"
              >
                <div className="min-w-0">
                  <p className="font-medium">{order.number}</p>
                  <p className="mt-1 text-sm text-muted">
                    {formatOrderDate(order.placed_at)} ·{" "}
                    {order.item_count} {order.item_count === 1 ? "item" : "items"}
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <StatusChip status={order.status} />
                  <span className="font-medium">{order.grand_total_display}</span>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}

      {/* Hrefs built here, not in the view: unlike the PLP there is no canonical-URL
          concern (the account area is noindex), so `?page=1` is emitted plainly. */}
      <Pagination
        page={page}
        prevHref={orders.previous === null ? null : `/account/orders?page=${page - 1}`}
        nextHref={orders.next === null ? null : `/account/orders?page=${page + 1}`}
      />
    </div>
  );
}
