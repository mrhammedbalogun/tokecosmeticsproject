/** Typed checkout fetchers + types. Server-side only (uses apiFetch) — mirrors
 * lib/catalog.ts. The single typed surface for every checkout read; pages/BFF import
 * from here. No React, no client code. Order reads live in lib/orders.ts. */
import { apiFetch } from "@/lib/api";

export interface Totals {
  subtotal: string; discount: string; delivery: string;
  tax: string; grand_total: string; currency: string;
  /** The market's name for its tax line ("VAT", "Sales Tax"). Optional so cached/old
   * quote payloads without it keep rendering — the UI falls back to "Tax". */
  tax_label?: string;
}
export interface QuoteResult { totals: Totals; coupon: { ok: boolean; error_code?: string } }
export interface DeliveryOption {
  /** `min_days`/`max_days` are the names the API actually uses (delivery/services.py).
   * These were `eta_*_days` here, and the fixtures were written from this type rather
   * than from a real response — so the tests passed while every customer saw
   * "undefined days" on every delivery option. */
  /** number for DeliveryOption rows, string ("pz:{pk}") for partner zones (Plan-39).
   * Opaque either way — it only ever round-trips back to the API. */
  id: number | string;
  name: string; price: string | null;
  min_days: number; max_days: number; quote_required: boolean;
  /** Present on carrier rows (delivery/services.py): "gig" + "pickup" marks the
   * centre-pickup option, which reveals the centre picker (32b slice 4). */
  carrier_code?: string;
  carrier_service?: string;
  /** "store" marks the Toke store-pickup option (Plan-40) — DeliveryStep branches
   * on it, so it rides the type even though DB rows also carry a kind. */
  kind?: string;
  /** Partner options only (Plan-39): the landmarks this LCDA rate covers, rendered
   * as an "Areas covered: …" line so the customer can tell which card is theirs. */
  areas_covered?: string;
  /** Store-pickup option only (Plan-40): the Toke stores in the address's state,
   * embedded in the option so the picker needs no second fetch. */
  stores?: PickupStoreOption[];
}

/** One Toke store on the store-pickup option (Plan-40) — `id` is the backend's
 * SenderLocation pk, round-tripped as `pickup_store_id` at placement. */
export interface PickupStoreOption {
  id: number;
  name: string;
  address: string;
  phone: string;
  distance_km?: number;
}

/** One row of GET /api/checkout/gig-centres — `id` is GIG's centre id (not a PK). */
export interface GigCentreOption {
  id: number;
  name: string;
  address: string;
  distance_km: number;
}
export interface PaymentMethod {
  gateway: string;
  sort_order: number;
  /** The market's payment instructions — admin-authored rich HTML, nh3-sanitised on
   * the backend (today only bank_transfer sends one). Non-empty -> the method card
   * offers a "Read payment instructions" link that opens them in a modal. */
  instructions?: string;
}

/** Public (AllowAny) — safe with apiFetch + country. */
export async function getPaymentMethods(country: string) {
  return apiFetch<PaymentMethod[]>(`/checkout/payment-methods/?country=${country}`, {
    country, cache: "no-store",
  });
}
