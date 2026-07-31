/**
 * The status filter, plus the needs-attention entry.
 *
 * A Server Component: every control is a link, so the URL stays the truth about what is on
 * screen and a filtered queue can be pasted into a message. Same reasoning as the audit
 * log's filters.
 *
 * NEEDS ATTENTION IS SEPARATED, and deliberately not shown as another status.
 * `review_reason` is orthogonal to the lifecycle — `orders/models.py` says so, and there is
 * no `needs_review` status to filter on. A processing order can need review and so can an
 * expired one. Rendering it alongside the statuses would teach an operator a category the
 * system does not have.
 */
import Link from "next/link";
import { ORDER_STATUSES, ordersQueryString, statusLabel, type OrderFilters } from "@/lib/orders";

const BASE = "rounded-full border px-3 py-1 text-sm transition";

export function OrderStatusTabs({ filters }: { filters: OrderFilters }) {
  // Changing a filter returns to page 1. Keeping page 7 while narrowing is how somebody
  // lands on an empty page and concludes the filter matched nothing.
  const href = (next: Partial<OrderFilters>) => {
    const qs = ordersQueryString({ ...filters, ...next, page: 1 });
    return qs ? `/orders?${qs}` : "/orders";
  };

  const chip = (active: boolean, extra = "") =>
    `${BASE} ${active ? "border-accent bg-accent/10 font-medium text-accent" : "border-line text-muted hover:border-accent"} ${extra}`;

  const allActive = !filters.status && !filters.needs_attention;

  return (
    <nav aria-label="Filter orders by status" className="flex flex-wrap items-center gap-2">
      <Link
        href={href({ status: undefined, needs_attention: undefined })}
        aria-current={allActive ? "page" : undefined}
        className={chip(allActive)}
      >
        All
      </Link>

      <Link
        href={href({ status: undefined, needs_attention: true })}
        aria-current={filters.needs_attention ? "page" : undefined}
        className={chip(
          Boolean(filters.needs_attention),
          filters.needs_attention ? "" : "border-warn/40 text-warn",
        )}
      >
        Needs attention
      </Link>

      <span aria-hidden="true" className="mx-1 h-4 w-px bg-line" />

      {ORDER_STATUSES.map((status) => {
        const active = filters.status === status && !filters.needs_attention;
        return (
          <Link
            key={status}
            href={href({ status, needs_attention: undefined })}
            aria-current={active ? "page" : undefined}
            className={chip(active)}
          >
            {statusLabel(status)}
          </Link>
        );
      })}
    </nav>
  );
}
