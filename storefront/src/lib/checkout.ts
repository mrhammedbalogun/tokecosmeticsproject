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
  id: number; name: string; price: string | null;
  eta_min_days: number; eta_max_days: number; quote_required: boolean;
}
export interface PaymentMethod { gateway: string; sort_order: number }
export interface OrderItem {
  product_name: string; variant_name: Record<string, string>; sku: string;
  quantity: number; unit_price: string; line_total: string;
  unit_price_display: string; line_total_display: string; image_url: string | null;
}
export interface OrderDetail {
  number: string; status: string; placed_at: string; currency: string;
  subtotal: string; discount_total: string; shipping_total: string; tax_total: string;
  grand_total: string; grand_total_display: string; delivery_option_name: string | null;
  shipping_address: Record<string, unknown> | null; billing_address: Record<string, unknown> | null;
  customer_note: string; items: OrderItem[];
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
