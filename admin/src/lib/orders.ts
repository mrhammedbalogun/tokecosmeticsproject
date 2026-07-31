/**
 * Shapes and query handling for the admin orders list. No fetching — that is
 * `app/(shell)/orders/page.tsx`.
 *
 * THE FILTER VOCABULARY IS THE ENDPOINT'S. `AdminOrderListView.get_queryset` reads
 * `status`, `country`, `source`, `gateway`, `placed_after`, `placed_before`,
 * `needs_attention` and `search` and ignores everything else, so forwarding anything else
 * would give an operator a control that silently does nothing.
 */
import { PAGE_SIZE } from "@/lib/pagination";

export { PAGE_SIZE };

/** `ALLOWED_TRANSITIONS` in `backend/apps/orders/state.py`, in lifecycle order rather
 *  than alphabetical — that is the order somebody thinks about them in. */
export const ORDER_STATUSES = [
  "pending_payment",
  "processing",
  "shipped",
  "delivered",
  "completed",
  "on_hold",
  "expired",
  "cancelled",
  "refunded",
] as const;

export type OrderStatus = (typeof ORDER_STATUSES)[number];

export function isOrderStatus(value: string): value is OrderStatus {
  return (ORDER_STATUSES as readonly string[]).includes(value);
}

export interface OrderRow {
  number: string;
  status: OrderStatus;
  review_reason: string;
  placed_at: string | null;
  email: string;
  country: string;
  currency: string;
  grand_total: string;
  grand_total_display: string;
  source: string;
}

export interface OrderPage {
  count: number;
  next: string | null;
  previous: string | null;
  results: OrderRow[];
}

export interface OrderFilters {
  status?: OrderStatus;
  country?: string;
  gateway?: string;
  search?: string;
  placed_after?: string;
  placed_before?: string;
  needs_attention?: boolean;
  page: number;
}

const TEXT_KEYS = ["country", "gateway", "search", "placed_after", "placed_before"] as const;

export function parseOrderFilters(params: URLSearchParams): OrderFilters {
  const filters: OrderFilters = { page: parsePage(params.get("page")) };

  const status = params.get("status")?.trim();
  // An unrecognised status is DROPPED rather than forwarded: the backend would filter to
  // nothing and the operator would read an empty table as "no orders" rather than as a
  // typo in the URL.
  if (status && isOrderStatus(status)) filters.status = status;

  for (const key of TEXT_KEYS) {
    const value = params.get(key)?.trim();
    // Blank is ABSENT. A GET form submits every field it contains, so an untouched form
    // would otherwise send five filters that each match everything.
    if (value) filters[key] = value;
  }

  if (params.get("needs_attention") === "true") filters.needs_attention = true;

  return filters;
}

function parsePage(raw: string | null): number {
  if (!raw || !/^\d+$/.test(raw)) return 1;
  const page = Number(raw);
  return page >= 1 ? page : 1;
}

export function ordersQueryString(filters: OrderFilters): string {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  for (const key of TEXT_KEYS) {
    const value = filters[key];
    if (value) params.set(key, value);
  }
  // The endpoint tests for the literal string "true", so a bare `?needs_attention` or a
  // `1` would be silently ignored.
  if (filters.needs_attention) params.set("needs_attention", "true");
  if (filters.page > 1) params.set("page", String(filters.page));
  return params.toString();
}

/**
 * The reasons an order is flagged, as separate items.
 *
 * `review_reason` accumulates through `_append_reason`
 * (`backend/apps/payments/services.py`), **newline-separated**. One order can carry
 * several — an overpayment and a duplicate reference, say.
 *
 * IT SPLITS ON A NEWLINE AND NOT ON "; ", and that is the whole point of the separator.
 * The backend used to join with `"; "`, which one of the reasons contains:
 *
 *     "possible double payment — order already processing; refund payment 7"
 *
 * Splitting on that turned one sentence into two fragments, the second reading as a bare
 * instruction. It also broke the backend's own dedupe, so the sentence could be stored
 * twice. Both were fixed by changing the separator to something no reason contains.
 *
 * NEVER PARSED FOR MEANING. Each is a human sentence with amounts baked in ("overpaid by
 * ₦500 — refund the difference"), and anything that pattern-matched them would break the
 * first time somebody rewords one. Split and display, nothing more.
 */
export function reviewReasons(order: { review_reason: string }): string[] {
  return order.review_reason
    .split("\n")
    .map((reason) => reason.trim())
    .filter(Boolean);
}

/** Human label for a status. The API's values are lowercase machine tokens. */
export function statusLabel(status: string): string {
  return status.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

/**
 * Which statuses read as "this order is still work".
 *
 * Used only to tint the table — the pipeline is the backend's business. `on_hold` counts
 * because Plan-23 parks 879 migrated orders there for triage, and they are all work.
 */
export const OPEN_STATUSES: readonly string[] = [
  "pending_payment",
  "processing",
  "shipped",
  "on_hold",
];
