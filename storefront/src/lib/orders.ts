/** Typed order fetchers + types. Server-side only — mirrors lib/checkout.ts. Shared by
 * the confirmation page and the account order pages; each page owns its own fetch, so
 * nothing here caches or memoises across callers.
 *
 * Not every fetcher here is session-based: the backend's order detail endpoint is
 * AllowAny and also serves a signed `?token=` tracking link, so a public token fetcher
 * (plain apiFetch, no session) belongs in this module alongside the authed ones. */
import { fetchWithAuthOrBounce } from "@/lib/session";

export interface OrderItem {
  /** A pre-joined STRING ("Size: 150ml"), not the cart's {option: value} map — an order
   * line is a point-in-time snapshot and OrderItem.variant_name is a CharField on the
   * backend. Typing it as a Record made the confirmation page call Object.values() on a
   * string and render it one character at a time ("S / i / z / e / ..."). */
  product_name: string; variant_name: string; sku: string;
  quantity: number; unit_price: string; line_total: string;
  unit_price_display: string; line_total_display: string; image_url: string | null;
}
export interface OrderDetail {
  number: string; status: string; placed_at: string; currency: string;
  subtotal: string; discount_total: string; shipping_total: string; tax_total: string;
  grand_total: string; grand_total_display: string; delivery_option_name: string | null;
  shipping_address: Record<string, unknown> | null; billing_address: Record<string, unknown> | null;
  customer_note: string; payment_gateway: string; items: OrderItem[];
}

/** The list endpoint's row (backend `OrderListSerializer`) — a strict subset of
 * OrderDetail plus `item_count`, which counts UNITS (sum of quantities), not lines. */
export interface OrderListItem {
  number: string; status: string; placed_at: string; currency: string;
  grand_total: string; grand_total_display: string; item_count: number;
  items: OrderItem[];
}

/** DRF's PageNumberPagination envelope. Structurally identical to catalog.ts's copy and
 * deliberately not shared: the two modules describe different APIs that happen to use the
 * same pagination class today, and a cross-import would couple order fetchers to the
 * catalog module for a three-field type. */
export interface Paginated<T> {
  count: number; next: string | null; previous: string | null; results: T[];
}

/**
 * Authed order detail, called from the confirmation page — a SERVER COMPONENT, hence
 * `fetchWithAuthOrBounce` rather than `fetchWithAuth`: a Server Component cannot persist
 * a rotated token, so refreshing here would blacklist the customer's refresh token and
 * end their session behind a page that still rendered correctly.
 *
 * `currentPath` is where the bounce sends the user back to, so it must be the page's own
 * path, not this endpoint's.
 *
 * There is no anonymous path to guard *here*: `orders/views.py` 403s a caller with no
 * auth and no signed tracking token, and neither the confirmation page nor the account
 * order-detail page ever carries a token.
 *
 * The endpoint itself is AllowAny and does serve a signed `?token=` tracking link — a
 * public/token caller must use the dedicated tracking fetcher (plain apiFetch, no
 * session), never this function, which would bounce a guest to login instead.
 */
export async function getOrder(number: string, country: string, currentPath: string) {
  return fetchWithAuthOrBounce<OrderDetail>(`/orders/${number}/`, currentPath, {
    country, cache: "no-store",
  });
}

/**
 * The signed-in shopper's own orders, newest first (the backend owner-filters and orders
 * by `-placed_at`; IsAuthenticated, so this call IS the page's auth gate — no extra
 * requireAuth on top of it).
 *
 * `no-store` because order status changes out from under any cache, and the response is
 * per-user: a shared cache entry here would serve one customer's orders to another.
 *
 * DRF 404s a page beyond the last one, so the caller must map ApiError 404 → notFound().
 */
export async function getOrders(page: number, currentPath: string) {
  return fetchWithAuthOrBounce<Paginated<OrderListItem>>(`/orders/?page=${page}`, currentPath, {
    cache: "no-store",
  });
}
