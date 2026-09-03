import { formatMoney } from "@/lib/country";
import type { OrderDetail } from "@/lib/orders";
import { referralDiscountLabel } from "@/lib/referral";

/** Only the money fields, so a caller never has to hold a whole OrderDetail to render
 * the totals. */
type OrderMoney = Pick<
  OrderDetail,
  | "currency" | "subtotal" | "discount_total" | "shipping_total" | "tax_total"
  | "tax_label" | "grand_total_display"
  | "referral_discount_total" | "referral_discount_percent"
  | "combo_discount_total"
>;

export function OrderTotals({ order }: { order: OrderMoney }) {
  return (
    <dl className="mt-6 space-y-2 border-t border-line pt-4 text-sm">
      <div className="flex justify-between gap-4">
        <dt className="text-muted">Subtotal</dt>
        <dd>{formatMoney(order.subtotal, order.currency)}</dd>
      </div>
      {/* First of the three discount lines, matching the order they come off in
          `compute_totals` — and matching the confirmation email and the invoice, so a
          customer holding all three documents sees one story. Absent, not zero, on every
          order placed before the column existed. */}
      {(order.combo_discount_total ?? "0.00") !== "0.00" && (
        <div className="flex justify-between gap-4">
          <dt className="text-muted">Combo saving</dt>
          <dd>−{formatMoney(order.combo_discount_total!, order.currency)}</dd>
        </div>
      )}
      {order.discount_total !== "0.00" && (
        <div className="flex justify-between gap-4">
          <dt className="text-muted">Discount</dt>
          <dd>−{formatMoney(order.discount_total, order.currency)}</dd>
        </div>
      )}
      {/* Named separately from the coupon line above so "why is this less than the
          products" is answerable from the order itself. Absent, not zero, on every order
          placed before the column existed. */}
      {(order.referral_discount_total ?? "0.00") !== "0.00" && (
        <div className="flex justify-between gap-4">
          <dt className="text-muted">
            {referralDiscountLabel(order.referral_discount_percent)}
          </dt>
          <dd>−{formatMoney(order.referral_discount_total!, order.currency)}</dd>
        </div>
      )}
      <div className="flex justify-between gap-4">
        <dt className="text-muted">Delivery</dt>
        <dd>{formatMoney(order.shipping_total, order.currency)}</dd>
      </div>
      {order.tax_total !== "0.00" && (
        <div className="flex justify-between gap-4">
          <dt className="text-muted">{order.tax_label || "Tax"}</dt>
          <dd>{formatMoney(order.tax_total, order.currency)}</dd>
        </div>
      )}
      <div className="flex justify-between gap-4 border-t border-line pt-2 text-base font-medium">
        <dt>Total</dt>
        <dd>{order.grand_total_display}</dd>
      </div>
    </dl>
  );
}
