"use client";

/**
 * The buy panel: the price, the saving, how many, and one button.
 *
 * ── WHY THE COMPARISON IS SHOWN AS TWO NUMBERS AND NOT ONE ──────────────────────────
 *
 * The bundle price alone is unpersuasive and the percentage alone is unverifiable. Both,
 * with the struck-through "bought separately" figure the customer can check against the
 * product pages linked below, is the whole argument for a combo — and every number here
 * comes from the API already resolved, so the page cannot claim a saving the till does
 * not give.
 *
 * ── THE TWO REFUSALS ARE DIFFERENT SENTENCES ────────────────────────────────────────
 *
 * `combo_out_of_stock` means the scarcest thing in the box ran out — come back. Whereas
 * `combo_unavailable` means it is not sold in this market at all, which no amount of
 * waiting fixes. Collapsing them into "something went wrong" is how a shopper ends up
 * refreshing a page that will never work.
 */
import { useState } from "react";
import { useRouter } from "next/navigation";
import {
  isComboSoldOut,
  isComboUnavailable,
  useCart,
} from "@/hooks/useCart";
import { openCartDrawer } from "@/lib/cart-ui";
import { ComboSavingBadge } from "@/components/combo/ComboSavingBadge";
import type { ComboDetail } from "@/lib/combos";
import { formatMoney } from "@/lib/country";
import { newEventId, track } from "@/lib/tracking/events";

export function ComboBuyBox({
  combo,
  deliveryLine,
}: {
  combo: ComboDetail;
  deliveryLine: string;
}) {
  const { addCombo } = useCart();
  const router = useRouter();
  const [qty, setQty] = useState(1);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const pricing = combo.pricing;
  // The server's own cap, so the stepper stops where the stock does instead of letting
  // somebody pick five and be told at the till.
  const max = Math.max(1, combo.max_quantity || 1);

  async function onAdd() {
    if (!pricing) return;
    setBusy(true);
    setProblem(null);
    try {
      await addCombo.mutateAsync({ comboSlug: combo.slug, quantity: qty });
      // After the mutation resolves, never before: an add that then failed on stock is
      // not a conversion.
      track({
        name: "add_to_cart",
        eventId: newEventId(),
        currency: pricing.currency,
        value: Number(pricing.amount) * qty,
        items: combo.items.map((item) => ({
          sku: item.sku,
          name: item.product_name,
          price: Number(item.unit_price ?? 0),
          quantity: item.quantity * qty,
        })),
      });
      openCartDrawer();
    } catch (err) {
      if (isComboSoldOut(err)) {
        setProblem("This combo just sold out — one of the products in it has run low.");
        router.refresh();
      } else if (isComboUnavailable(err)) {
        setProblem("This combo isn't sold in your country.");
      } else {
        setProblem("That didn't go through. Please try again.");
      }
    } finally {
      setBusy(false);
    }
  }

  if (!pricing) {
    return (
      <p className="rounded-[var(--radius-card)] border border-line bg-surface p-4 text-sm text-muted">
        This combo isn&rsquo;t available in your country right now.
      </p>
    );
  }

  return (
    <div className="rounded-[var(--radius-card)] border border-line bg-surface p-5 shadow-sm">
      <ComboSavingBadge pricing={pricing} />

      <div className="mt-3 flex flex-wrap items-baseline gap-3">
        <p className="text-3xl font-medium">
          {formatMoney(pricing.amount, pricing.currency)}
        </p>
        <p className="text-sm text-muted">
          <span className="sr-only">Bought separately</span>
          <s>{formatMoney(pricing.components_total, pricing.currency)}</s>{" "}
          <span className="text-xs">bought separately</span>
        </p>
      </div>

      <p className="mt-1 text-sm text-accent">
        You save {formatMoney(pricing.saving, pricing.currency)} on this box.
      </p>

      {combo.in_stock ? (
        <>
          <div className="mt-5 flex flex-wrap items-center gap-4">
            <div className="inline-flex items-center rounded-full border border-line">
              <button
                type="button"
                aria-label="Decrease quantity"
                disabled={qty <= 1}
                onClick={() => setQty((q) => Math.max(1, q - 1))}
                className="px-4 py-2 text-lg disabled:opacity-30"
              >
                −
              </button>
              <span aria-live="polite" className="w-10 text-center text-sm font-medium">
                {qty}
              </span>
              <button
                type="button"
                aria-label="Increase quantity"
                disabled={qty >= max}
                onClick={() => setQty((q) => Math.min(max, q + 1))}
                className="px-4 py-2 text-lg disabled:opacity-30"
              >
                +
              </button>
            </div>
            {max <= 5 && (
              <p className="text-xs text-muted">
                Only {max} {max === 1 ? "box" : "boxes"} left
              </p>
            )}
          </div>

          <button
            type="button"
            onClick={onAdd}
            disabled={busy}
            className="mt-4 w-full rounded-full bg-accent px-6 py-3.5 text-sm font-semibold uppercase tracking-[0.08em] text-white transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {busy ? "Adding…" : "Add combo to bag"}
          </button>

          {qty > 1 && (
            <p className="mt-2 text-center text-sm text-muted">
              {qty} boxes ={" "}
              <span className="font-medium text-foreground">
                {formatMoney(String(Number(pricing.amount) * qty), pricing.currency)}
              </span>{" "}
              — saving {formatMoney(String(Number(pricing.saving) * qty), pricing.currency)}
            </p>
          )}
        </>
      ) : (
        <p className="mt-5 rounded-full border border-line px-6 py-3 text-center text-sm font-semibold uppercase tracking-[0.08em] text-muted">
          Sold Out
        </p>
      )}

      {problem && (
        <p role="alert" className="mt-3 text-sm text-accent-strong">
          {problem}
        </p>
      )}

      <p className="mt-4 border-t border-line pt-3 text-xs text-muted">{deliveryLine}</p>
    </div>
  );
}
