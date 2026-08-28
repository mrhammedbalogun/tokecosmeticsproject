/** Shape returned by the Business Decisions admin endpoint (2026-08-27). Mirrors
 * apps/core/serializers.py — BusinessDecisionsSerializer.
 *
 * The percentages arrive as STRINGS, not numbers, because that is how DRF renders a
 * DecimalField and because a rate is money-adjacent: parsing "10.00" into a float and
 * rendering it back is how a 12.5% rate becomes 12.499999999999998 in an input box. */

export interface BusinessDecisionsRow {
  referrer_commission_percent: string;
  customer_discount_percent: string;
  customer_discount_first_order_only: boolean;
}
