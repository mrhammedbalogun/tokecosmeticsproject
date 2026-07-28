/** Typed order fetchers + types. Server-side only (uses session helpers) — mirrors
 * lib/checkout.ts. Shared by the confirmation page and the account order pages; each
 * page owns its own fetch, so nothing here caches or memoises across callers. */
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

/**
 * Authed order detail, called from the confirmation page — a SERVER COMPONENT, hence
 * `fetchWithAuthOrBounce` rather than `fetchWithAuth`: a Server Component cannot persist
 * a rotated token, so refreshing here would blacklist the customer's refresh token and
 * end their session behind a page that still rendered correctly.
 *
 * `currentPath` is where the bounce sends the user back to, so it must be the page's own
 * path, not this endpoint's.
 *
 * There is no anonymous path to guard: `orders/views.py` 403s a caller with no auth and
 * no signed tracking token, and this page never carries one.
 */
export async function getOrder(number: string, country: string, currentPath: string) {
  return fetchWithAuthOrBounce<OrderDetail>(`/orders/${number}/`, currentPath, {
    country, cache: "no-store",
  });
}
