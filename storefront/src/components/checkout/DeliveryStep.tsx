"use client";
import { useEffect, useState } from "react";
import { useCheckout } from "@/components/checkout/CheckoutContext";
import { useCart } from "@/hooks/useCart";
import { formatMoney, symbolFor } from "@/lib/country";
import type { DeliveryOption } from "@/lib/checkout";

/** Step 3 of checkout: delivery options for the address chosen in step 2 (Plan-14
 * Task 8).
 *
 * - Fetches `/api/checkout/delivery-options?address_id=..&cart_id=..` whenever
 *   `selections.addressId` changes (CheckoutContext's `setAddress` already cleared
 *   any stale `deliveryOptionId` and un-completed this step when the address
 *   changed, so re-fetching here is the only thing this step owns).
 * - Options are `role="radio"` buttons, same pattern as AddressStep, so re-clicking
 *   an already-selected option still fires (a native radio's change event doesn't
 *   fire again once checked).
 * - Rest-of-World addresses may return `quote_required` options with `price: null`
 *   — the real freight quote happens after checkout (Plan-14a), so those options
 *   are still selectable here, just labelled "Quoted after checkout".
 */
interface FetchResult {
  addressId: number;
  cartId: string;
  options: DeliveryOption[];
  error: string | null;
}

export function DeliveryStep() {
  const { selections, complete } = useCheckout();
  const { cart } = useCart();
  const addressId = selections.addressId;
  const cartId = cart.id;

  // Keyed by the (addressId, cartId) it was fetched for — never reset synchronously
  // on a dependency change (that would call setState directly in the effect body).
  // Instead, staleness is derived at render time below: if the last result doesn't
  // match the current addressId/cartId, treat it as "still loading". This also
  // doubles as the guard against a slow, now-superseded response landing after a
  // fast address change — combined with the `cancelled` flag, which stops that
  // response from calling setState at all.
  const [result, setResult] = useState<FetchResult | null>(null);

  useEffect(() => {
    if (!addressId || !cartId) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(
          `/api/checkout/delivery-options?address_id=${addressId}&cart_id=${encodeURIComponent(cartId)}`
        );
        const data = await res.json().catch(() => null);
        if (cancelled) return;
        if (!res.ok || !Array.isArray(data)) {
          setResult({ addressId, cartId, options: [], error: "Couldn't load delivery options — please try again." });
          return;
        }
        setResult({ addressId, cartId, options: data as DeliveryOption[], error: null });
      } catch {
        if (cancelled) return;
        setResult({ addressId, cartId, options: [], error: "Couldn't load delivery options — please try again." });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [addressId, cartId]);

  const stale = !result || result.addressId !== addressId || result.cartId !== cartId;
  const options = stale ? null : result.options;
  const error = stale ? null : result.error;

  function handleSelect(option: DeliveryOption) {
    const price = option.quote_required || option.price === null
      ? "Quoted after checkout"
      : formatMoney(option.price, cart.currency, symbolFor(cart.currency));
    complete(3, { deliveryOptionId: option.id, deliveryDisplay: `${option.name} — ${price}` });
  }

  if (!addressId) {
    return <p className="text-sm text-muted">Choose a delivery address first.</p>;
  }

  if (options === null) {
    return <p className="text-sm text-muted">Loading delivery options…</p>;
  }

  return (
    <div className="space-y-3">
      {error && (
        <p role="alert" className="text-sm text-red-700">
          {error}
        </p>
      )}

      {!error && options.length === 0 && (
        <p className="text-sm text-muted">
          No delivery options for this address — please try another address.
        </p>
      )}

      {options.length > 0 && (
        <div role="radiogroup" aria-label="Delivery options" className="space-y-3">
          {options.map((option) => {
            const checked = selections.deliveryOptionId === option.id;
            const quoted = option.quote_required || option.price === null;
            const priceLabel = quoted
              ? "Quoted after checkout"
              : formatMoney(option.price as string, cart.currency, symbolFor(cart.currency));
            const etaLabel =
              option.eta_min_days === option.eta_max_days
                ? `${option.eta_min_days} days`
                : `${option.eta_min_days}–${option.eta_max_days} days`;
            return (
              <button
                key={option.id}
                type="button"
                role="radio"
                aria-checked={checked}
                onClick={() => handleSelect(option)}
                className={`block w-full rounded-[var(--radius-card)] border p-4 text-left text-sm transition-colors ${
                  checked ? "border-accent bg-accent/5" : "border-line hover:border-accent/60"
                }`}
              >
                <span className="flex items-center justify-between gap-2 font-medium">
                  <span>{option.name}</span>
                  <span>{priceLabel}</span>
                </span>
                <span className="mt-1 block text-muted">{etaLabel}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
