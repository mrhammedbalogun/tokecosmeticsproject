import { formatMoney } from "@/lib/country";
import type { Totals } from "@/lib/checkout";

/** Module-scoped (not nested in OrderSummary) — eslint's react-hooks/static-components
 * rule flags components declared inside a render function, since they'd be recreated
 * (and lose state) on every render. This one is stateless, but the rule doesn't know
 * that, and hoisting is the correct fix regardless. */
function Row({
  label,
  value,
  currency,
  strong = false,
  neg = false,
}: {
  label: string;
  value: string;
  currency: string;
  strong?: boolean;
  neg?: boolean;
}) {
  return (
    <div className={`flex justify-between ${strong ? "font-medium text-base" : "text-sm text-muted"}`}>
      <span>{label}</span>
      <span>
        {neg ? "−" : ""}
        {formatMoney(value, currency)}
      </span>
    </div>
  );
}

/** Presentational totals box, reused on the cart page (subtotal-only fallback for
 * guests) and in checkout (full totals once a quote is available). Never computes
 * money itself — every value is a server-formatted string passed straight through
 * formatMoney for grouping/symbol only. */
export function OrderSummary({
  totals,
  fallbackSubtotal,
  currency,
}: {
  totals: Totals | null;
  fallbackSubtotal: string;
  currency: string;
}) {
  if (!totals) {
    return (
      <div className="space-y-2">
        <Row label="Subtotal" value={fallbackSubtotal} currency={currency} />
        <p className="text-xs text-muted">Delivery &amp; taxes calculated at checkout.</p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <Row label="Subtotal" value={totals.subtotal} currency={currency} />
      {totals.discount !== "0.00" && (
        <Row label="Discount" value={totals.discount} currency={currency} neg />
      )}
      <Row label="Delivery" value={totals.delivery} currency={currency} />
      <Row label="Tax" value={totals.tax} currency={currency} />
      <div className="mt-2 border-t border-line pt-2">
        <Row label="Total" value={totals.grand_total} currency={currency} strong />
      </div>
    </div>
  );
}
