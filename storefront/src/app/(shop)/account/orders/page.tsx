import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ApiError } from "@/lib/api";
import { first } from "@/lib/search-params";
import { getOrders, type OrderListItem, type Paginated } from "@/lib/orders";
import { StatusChip } from "@/components/orders/StatusChip";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

// The account layout already sets robots noindex for everything beneath it.
export const metadata: Metadata = { title: "My orders" };

/** Untrusted URL input → a page number DRF will accept. Anything that is not a positive
 * integer (0, -1, 1.5, "abc", a repeated param) falls back to the first page rather than
 * being forwarded verbatim — same discipline as parsePlpParams. */
function parsePage(raw: string | string[] | undefined): number {
  const page = Number(first(raw));
  return Number.isInteger(page) && page > 0 ? page : 1;
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

const DATE = new Intl.DateTimeFormat("en-GB", {
  day: "numeric", month: "short", year: "numeric",
});

export default async function OrdersPage({ searchParams }: { searchParams: SearchParams }) {
  const page = parsePage((await searchParams).page);
  // The bounce target must be this exact URL, page included, or a renewal mid-history
  // dumps the customer back on page 1.
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
                href={`/account/orders/${order.number}`}
                className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 rounded-[var(--radius-card)] border border-line p-4 transition-colors hover:bg-beige"
              >
                <div className="min-w-0">
                  <p className="font-medium">{order.number}</p>
                  <p className="mt-1 text-sm text-muted">
                    {DATE.format(new Date(order.placed_at))} ·{" "}
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

      {/* Driven by the API's own next/previous links, never a computed page count, so we
          never link past the last page (which DRF 404s). */}
      {(orders.previous !== null || orders.next !== null) && (
        <nav aria-label="Pagination" className="mt-8 flex items-center justify-center gap-2">
          {orders.previous !== null && (
            <Link
              rel="prev"
              href={`/account/orders?page=${page - 1}`}
              className="rounded-full border border-line px-4 py-2 text-sm hover:border-accent"
            >
              ← Prev
            </Link>
          )}
          <span className="px-3 text-sm text-muted">Page {page}</span>
          {orders.next !== null && (
            <Link
              rel="next"
              href={`/account/orders?page=${page + 1}`}
              className="rounded-full border border-line px-4 py-2 text-sm hover:border-accent"
            >
              Next →
            </Link>
          )}
        </nav>
      )}
    </div>
  );
}
