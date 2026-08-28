/**
 * The admin order detail's shape, and the small decisions about rendering it.
 *
 * Mirrors `AdminOrderSerializer` (`backend/apps/orders/serializers.py`) — including the
 * payments block and `allowed_transitions`, both added in Plan-18a Task 1 because the
 * payment panel had nothing to read and the transition buttons had no legal set to render.
 */
import type { OrderStatus } from "@/lib/orders";

export interface OrderRefund {
  id: number;
  amount: string;
  status: string;
  reason: string;
  gateway_reference: string;
  created_by_email: string;
  created_at: string;
}

export interface OrderPayment {
  id: number;
  gateway: string;
  purpose: string;
  amount: string;
  currency: string;
  status: string;
  gateway_reference: string;
  created_at: string;
  refunds: OrderRefund[];
  /** What is left to refund, computed by the backend from the ledger. */
  refundable: string;
}

export interface OrderEvent {
  type: string;
  message: string;
  actor_name: string;
  created_at: string;
}

export interface OrderItem {
  product_name: string;
  variant_name: string;
  sku: string;
  quantity: number;
  unit_price: string;
  line_total: string;
  unit_price_display: string;
  line_total_display: string;
  image_url: string | null;
}

/** One move the ENDPOINT will accept, with the scope it needs. Not the raw state machine —
 *  see `get_allowed_transitions`. */
export interface AllowedTransition {
  status: string;
  requires_scope: string | null;
}

export interface OrderDetail {
  number: string;
  status: OrderStatus;
  review_reason: string;
  placed_at: string | null;
  email: string;
  phone: string;
  user_email: string;
  country: string;
  currency: string;
  subtotal: string;
  discount_total: string;
  /** The referred customer's discount (2026-08-27) and the rate it was given at.
   * Optional: orders placed before the columns existed carry neither. */
  referral_discount_total?: string;
  referral_discount_percent?: string;
  shipping_total: string;
  tax_total: string;
  /** The market's name for the tax line ("VAT", "Sales Tax"); optional so older
   * cached payloads keep rendering. */
  tax_label?: string;
  grand_total: string;
  grand_total_display: string;
  delivery_option_name: string;
  shipping_address: Record<string, string>;
  billing_address: Record<string, string>;
  customer_note: string;
  admin_note: string;
  tracking_carrier: string;
  tracking_number: string;
  source: string;
  legacy_number: string;
  /** Toke store-pickup snapshot from placement (Plan-40), or null. Presence relabels
   * the `shipped`/`delivered` moves ("Ready for pickup" / "Picked up") — the machine
   * is unchanged, only the words. */
  pickup_store?: { id: number; name: string; address: string; phone: string; state?: string } | null;
  items: OrderItem[];
  events: OrderEvent[];
  payments: OrderPayment[];
  allowed_transitions: AllowedTransition[];
}

/**
 * Whether this operator may make a given move.
 *
 * The scope comes from the API alongside the move, so this is a rendering decision and not
 * a second copy of the rule — the endpoint checks it again regardless
 * (`orders/views.py`, `ELEVATED_STATUSES`).
 */
export function mayTransition(
  transition: AllowedTransition,
  scopes: readonly string[],
): boolean {
  return !transition.requires_scope || scopes.includes(transition.requires_scope);
}

/**
 * A structured address as lines, in the order a label is written.
 *
 * The field is a plain JSON blob (`Order.shipping_address`) captured at checkout, so its
 * keys vary by country — NG carries state and LGA, GB carries a postcode. Known keys are
 * emitted in a sensible order and anything else is appended rather than dropped: an
 * address with a key we did not anticipate should still be postable.
 */
const ADDRESS_ORDER = [
  "first_name", "last_name", "company", "line1", "line2",
  // The NG landmark ("opposite Ikeja City Mall"), straight after the street lines and
  // before the locality — this is the line that gets a rider to the door, so a picker
  // reading the order must see it. Absent on non-NG and pre-2026-08-28 orders; the loop
  // below already skips missing keys.
  "landmark",
  "area", "city", "state", "postcode", "country", "phone",
];

export function addressLines(address: Record<string, string> | null | undefined): string[] {
  if (!address) return [];
  const seen = new Set<string>();
  const lines: string[] = [];

  for (const key of ADDRESS_ORDER) {
    const value = address[key];
    if (value) lines.push(String(value));
    seen.add(key);
  }
  for (const [key, value] of Object.entries(address)) {
    if (!seen.has(key) && value) lines.push(String(value));
  }
  return lines;
}

/** Totals in the order they belong on a receipt, skipping the zero rows that only add
 *  noise — but never `grand_total`, which is the number being paid. */
export function totalRows(
  order: OrderDetail,
): { label: string; value: string; strong?: boolean }[] {
  const rows: { label: string; value: string; strong?: boolean }[] = [
    { label: "Subtotal", value: order.subtotal },
  ];
  if (Number(order.discount_total) !== 0) {
    rows.push({ label: "Discount", value: `−${order.discount_total}` });
  }
  // Separate from the coupon line above: support answering "why was this order cheaper"
  // needs to see WHICH discount, and a merged number cannot tell them.
  if (Number(order.referral_discount_total ?? 0) !== 0) {
    const rate = (order.referral_discount_percent ?? "").replace(/\.0+$/, "");
    rows.push({
      label: rate && Number(rate) > 0 ? `Referral discount (${rate}%)` : "Referral discount",
      value: `−${order.referral_discount_total}`,
    });
  }
  if (Number(order.shipping_total) !== 0) {
    rows.push({ label: "Delivery", value: order.shipping_total });
  }
  if (Number(order.tax_total) !== 0) {
    rows.push({ label: order.tax_label || "Tax", value: order.tax_total });
  }
  rows.push({ label: "Total", value: order.grand_total_display, strong: true });
  return rows;
}
