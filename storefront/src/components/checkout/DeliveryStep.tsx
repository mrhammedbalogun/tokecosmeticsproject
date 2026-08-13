"use client";
import { useEffect, useState } from "react";
import { useCheckout } from "@/components/checkout/CheckoutContext";
import { useCart } from "@/hooks/useCart";
import { formatMoney, symbolFor } from "@/lib/country";
import type { DeliveryOption, GigCentreOption } from "@/lib/checkout";

const isPickup = (o: DeliveryOption) =>
  o.carrier_code === "gig" && o.carrier_service === "pickup";

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

  // The centre picker (32b slice 4): opened by clicking the pickup option, fed by
  // /api/checkout/gig-centres. Keyed by addressId with the same staleness pattern.
  const [pickerOptionId, setPickerOptionId] = useState<number | null>(null);
  const [centres, setCentres] = useState<{
    addressId: number; list: GigCentreOption[]; error: string | null;
  } | null>(null);

  useEffect(() => {
    if (!addressId || pickerOptionId === null) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`/api/checkout/gig-centres?address_id=${addressId}`);
        const data = await res.json().catch(() => null);
        if (cancelled) return;
        if (!res.ok || !Array.isArray(data)) {
          setCentres({ addressId, list: [], error: "Couldn't load pickup centres — please try again." });
          return;
        }
        setCentres({ addressId, list: data as GigCentreOption[], error: null });
      } catch {
        if (cancelled) return;
        setCentres({ addressId, list: [], error: "Couldn't load pickup centres — please try again." });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [addressId, pickerOptionId]);

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
    if (isPickup(option)) {
      // Pickup needs a centre before the step can complete — open the picker.
      setPickerOptionId(option.id);
      return;
    }
    setPickerOptionId(null);
    const price = option.quote_required || option.price === null
      ? "Quoted after checkout"
      : formatMoney(option.price, cart.currency, symbolFor(cart.currency));
    complete(3, {
      deliveryOptionId: option.id,
      deliveryDisplay: `${option.name} — ${price}`,
      gigCentreId: undefined, // a door option never carries a centre
    });
  }

  function handleCentrePick(option: DeliveryOption, centre: GigCentreOption) {
    complete(3, {
      deliveryOptionId: option.id,
      gigCentreId: centre.id,
      deliveryDisplay: `${option.name} · ${centre.name}`,
    });
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
            const pickup = isPickup(option);
            const checked =
              selections.deliveryOptionId === option.id &&
              (!pickup || selections.gigCentreId !== undefined);
            const pickerOpen = pickup && (pickerOptionId === option.id || checked);
            const quoted = option.quote_required || option.price === null;
            const priceLabel = quoted
              ? "Quoted after checkout"
              : formatMoney(option.price as string, cart.currency, symbolFor(cart.currency));
            const etaLabel =
              option.min_days === option.max_days
                ? `${option.min_days} days`
                : `${option.min_days}–${option.max_days} days`;
            const centreList = centres && centres.addressId === addressId ? centres : null;
            return (
              <div key={option.id}>
                <button
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
                  {pickup && !pickerOpen && (
                    <span className="mt-2 block font-medium text-accent">
                      Select to see nearby pickup centres &rarr;
                    </span>
                  )}
                </button>
                {pickerOpen && (
                  <div className="mt-2 ml-4 space-y-2">
                    <p className="text-sm font-medium">Choose your pickup centre</p>
                    {centreList === null && <p className="text-sm text-muted">Loading centres…</p>}
                    {centreList?.error && (
                      <p role="alert" className="text-sm text-red-700">{centreList.error}</p>
                    )}
                    {centreList && !centreList.error && centreList.list.length === 0 && (
                      <p className="text-sm text-muted">
                        No pickup centres serve this address — choose another option.
                      </p>
                    )}
                    {centreList && centreList.list.length > 0 && (
                      <div role="radiogroup" aria-label="Pickup centres" className="space-y-2">
                        {centreList.list.map((centre) => {
                          const centreChecked =
                            checked && selections.gigCentreId === centre.id;
                          return (
                            <button
                              key={centre.id}
                              type="button"
                              role="radio"
                              aria-checked={centreChecked}
                              onClick={() => handleCentrePick(option, centre)}
                              className={`block w-full rounded-[var(--radius-card)] border p-3 text-left text-sm transition-colors ${
                                centreChecked
                                  ? "border-accent bg-accent/5"
                                  : "border-line hover:border-accent/60"
                              }`}
                            >
                              <span className="flex items-center justify-between gap-2 font-medium">
                                <span>{centre.name}</span>
                                <span className="text-muted">{centre.distance_km} km</span>
                              </span>
                              <span className="mt-1 block text-muted">{centre.address}</span>
                            </button>
                          );
                        })}
                        <p className="text-xs text-muted">
                          The delivery price for your centre is confirmed at review.
                        </p>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
