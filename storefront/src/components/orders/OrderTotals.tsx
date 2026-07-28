import { formatMoney, symbolFor } from "@/lib/country";
import type { OrderDetail } from "@/lib/orders";

/** Only the money fields, so a caller never has to hold a whole OrderDetail to render
 * the totals. */
type OrderMoney = Pick<
  OrderDetail,
  "currency" | "subtotal" | "discount_total" | "shipping_total" | "tax_total" | "grand_total_display"
>;

export function OrderTotals({ order }: { order: OrderMoney }) {
  const sym = symbolFor(order.currency);

  return (
    <dl className="mt-6 space-y-2 border-t border-line pt-4 text-sm">
      <div className="flex justify-between gap-4">
        <dt className="text-muted">Subtotal</dt>
        <dd>{formatMoney(order.subtotal, order.currency, sym)}</dd>
      </div>
      {order.discount_total !== "0.00" && (
        <div className="flex justify-between gap-4">
          <dt className="text-muted">Discount</dt>
          <dd>−{formatMoney(order.discount_total, order.currency, sym)}</dd>
        </div>
      )}
      <div className="flex justify-between gap-4">
        <dt className="text-muted">Delivery</dt>
        <dd>{formatMoney(order.shipping_total, order.currency, sym)}</dd>
      </div>
      <div className="flex justify-between gap-4">
        <dt className="text-muted">Tax</dt>
        <dd>{formatMoney(order.tax_total, order.currency, sym)}</dd>
      </div>
      <div className="flex justify-between gap-4 border-t border-line pt-2 text-base font-medium">
        <dt>Total</dt>
        <dd>{order.grand_total_display}</dd>
      </div>
    </dl>
  );
}
