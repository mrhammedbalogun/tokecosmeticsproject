/** Typed checkout fetchers + types. Server-side only (uses apiFetch/fetchWithAuth) —
 * mirrors lib/catalog.ts. The single typed surface for every checkout read; pages/BFF
 * import from here. No React, no client code. */
import { apiFetch } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";

export interface Totals {
  subtotal: string; discount: string; delivery: string;
  tax: string; grand_total: string; currency: string;
}
export interface QuoteResult { totals: Totals; coupon: { ok: boolean; error_code?: string } }
export interface DeliveryOption {
  /** `min_days`/`max_days` are the names the API actually uses (delivery/services.py).
   * These were `eta_*_days` here, and the fixtures were written from this type rather
   * than from a real response — so the tests passed while every customer saw
   * "undefined days" on every delivery option. */
  id: number; name: string; price: string | null;
  min_days: number; max_days: number; quote_required: boolean;
}
export interface PaymentMethod { gateway: string; sort_order: number }
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

/** Public (AllowAny) — safe with apiFetch + country. */
export async function getPaymentMethods(country: string) {
  return apiFetch<PaymentMethod[]>(`/checkout/payment-methods/?country=${country}`, {
    country, cache: "no-store",
  });
}
/** Authed. */
export async function getDeliveryOptions(addressId: number, cartId: string, country: string) {
  return fetchWithAuth<DeliveryOption[]>(
    `/checkout/delivery-options/?address_id=${addressId}&cart_id=${cartId}`,
    { country, cache: "no-store" });
}
export async function getOrder(number: string, country: string) {
  return fetchWithAuth<OrderDetail>(`/orders/${number}/`, { country, cache: "no-store" });
}
