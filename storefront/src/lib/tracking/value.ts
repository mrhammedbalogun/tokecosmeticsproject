/**
 * What a purchase is worth, in the browser — and it MUST agree with the server.
 *
 * `apps/marketing/value.py::purchase_value` computes this for the server-side event, and
 * the two halves of one deduplicated Purchase disagreeing about the amount is a
 * genuinely nasty bug: the platform keeps whichever arrived first, so reported revenue
 * would depend on whether the customer came back from the payment gateway.
 *
 * ── WHY THIS IS NOT A SECOND IMPLEMENTATION OF THE TAX RULE ─────────────────────────
 *
 * The server's `goods` basis subtracts the ITEM tax for a market whose prices INCLUDE
 * tax (Nigeria) and does not for a market where tax is added on top (GB/US/CA). That
 * branch is not repeated here, because the order document the storefront holds does not
 * carry `prices_include_tax` or `delivery_tax_total` — it would have to be guessed.
 *
 * Instead this uses the columns that mean the same thing on both sides for the case that
 * exists today: subtotal minus every discount. Every seeded country currently carries
 * `tax_rate_percent = 0.00`, so the two agree exactly. **The day tax is switched on for
 * a `prices_include_tax` market, they stop agreeing** — and the fix is to publish the
 * server's computed value on the order serialiser and read it here, not to re-derive the
 * branch in TypeScript. `apps/marketing/tests/test_value.py` pins the server half; this
 * comment is the record of the gap.
 */
import type { OrderDetail } from "@/lib/orders";

export function purchaseValue(order: OrderDetail): number {
  const subtotal = Number(order.subtotal ?? 0);
  const discount = Number(order.discount_total ?? 0);
  const referral = Number(order.referral_discount_total ?? 0);
  // A bundle saving is a real price reduction like the other two, so the goods value an
  // ad platform is told about is net of it. Reporting the list price of parts the
  // customer did not pay for would inflate every combo order's ROAS.
  const combo = Number(order.combo_discount_total ?? 0);
  const value = subtotal - combo - discount - referral;
  // Never negative: all three discounts clamp to the subtotal on the backend, but a value
  // below zero is not something to forward to an ad platform.
  return value > 0 ? Number(value.toFixed(2)) : 0;
}
