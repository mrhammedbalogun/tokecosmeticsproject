import { formatMoney } from "@/lib/country";
import type { Totals } from "@/lib/checkout";
import { referralDiscountLabel } from "@/lib/referral";

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
  fallbackComboSaving,
  fallbackTotal,
  currency,
}: {
  totals: Totals | null;
  fallbackSubtotal: string;
  /** The cart's own combo saving, for the pre-quote view a guest always sees. Optional:
   *  a payload cached from before combos existed simply has none. */
  fallbackComboSaving?: string;
  /** `fallbackSubtotal` net of that saving — what the goods cost. */
  fallbackTotal?: string;
  currency: string;
}) {
  if (!totals) {
    const saving = fallbackComboSaving ?? "0.00";
    if (saving === "0.00") {
      return (
        <div className="space-y-2">
          <Row label="Subtotal" value={fallbackSubtotal} currency={currency} />
          <p className="text-xs text-muted">Delivery &amp; taxes calculated at checkout.</p>
        </div>
      );
    }
    return (
      <div className="space-y-2">
        <Row label="Items" value={fallbackSubtotal} currency={currency} />
        <Row label="Combo saving" value={saving} currency={currency} neg />
        <div className="mt-2 border-t border-line pt-2">
          <Row
            label="Subtotal"
            value={fallbackTotal ?? fallbackSubtotal}
            currency={currency}
            strong
          />
        </div>
        <p className="text-xs text-muted">Delivery &amp; taxes calculated at checkout.</p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <Row label="Subtotal" value={totals.subtotal} currency={currency} />
      {/* The bundles' saving, first of the three discounts because it comes off first
          (see `compute_totals`) and because it is the only one that is a property of the
          goods rather than of the shopper. `?? "0.00"` covers a quote payload cached
          from before the field existed. */}
      {(totals.combo_discount ?? "0.00") !== "0.00" && (
        <Row label="Combo saving" value={totals.combo_discount!} currency={currency} neg />
      )}
      {totals.discount !== "0.00" && (
        <Row label="Discount" value={totals.discount} currency={currency} neg />
      )}
      {/* The referred customer's own discount. Drawn only when there is one, so an
          un-referred cart looks exactly as it always did. `?? "0.00"` covers a quote
          payload cached from before the field existed. */}
      {(totals.referral_discount ?? "0.00") !== "0.00" && (
        <Row
          label={referralDiscountLabel(totals.referral_discount_percent)}
          value={totals.referral_discount!}
          currency={currency}
          neg
        />
      )}
      <Row label="Delivery" value={totals.delivery} currency={currency} />
      {totals.tax !== "0.00" && (
        <Row label={totals.tax_label || "Tax"} value={totals.tax} currency={currency} />
      )}
      <div className="mt-2 border-t border-line pt-2">
        <Row label="Total" value={totals.grand_total} currency={currency} strong />
      </div>
    </div>
  );
}
