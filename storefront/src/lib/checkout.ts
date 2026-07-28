/** Typed checkout fetchers + types. Server-side only (uses apiFetch) — mirrors
 * lib/catalog.ts. The single typed surface for every checkout read; pages/BFF import
 * from here. No React, no client code. Order reads live in lib/orders.ts. */
import { apiFetch } from "@/lib/api";

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

/** Public (AllowAny) — safe with apiFetch + country. */
export async function getPaymentMethods(country: string) {
  return apiFetch<PaymentMethod[]>(`/checkout/payment-methods/?country=${country}`, {
    country, cache: "no-store",
  });
}
