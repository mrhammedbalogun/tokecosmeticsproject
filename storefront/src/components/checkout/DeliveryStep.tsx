"use client";
import { useEffect, useState } from "react";
import { useCheckout } from "@/components/checkout/CheckoutContext";
import { useCart } from "@/hooks/useCart";
import { formatMoney } from "@/lib/country";
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
  addressKey: string;
  cartId: string;
  options: DeliveryOption[];
  error: string | null;
}

export function DeliveryStep() {
  const { selections, complete } = useCheckout();
  const { cart } = useCart();
  const addressId = selections.addressId;
  // Guest checkout (Plan-38): no saved address — the inline payload from AddressStep
  // is POSTed to the guest twins of the two endpoints below.
  const guestAddress = selections.guest ? selections.guestAddress : undefined;
  const cartId = cart.id;
  // One staleness key for both modes: the saved-address id, or the guest payload's
  // own JSON (stable — AddressStep replaces the object only on re-submit).
  const addressKey = guestAddress ? JSON.stringify(guestAddress) : addressId ? String(addressId) : "";

  // Keyed by the (addressKey, cartId) it was fetched for — never reset synchronously
  // on a dependency change (that would call setState directly in the effect body).
  // Instead, staleness is derived at render time below: if the last result doesn't
  // match the current addressKey/cartId, treat it as "still loading". This also
  // doubles as the guard against a slow, now-superseded response landing after a
  // fast address change — combined with the `cancelled` flag, which stops that
  // response from calling setState at all.
  const [result, setResult] = useState<FetchResult | null>(null);

  // The centre picker (32b slice 4): opened by clicking the pickup option, fed by
  // /api/checkout/gig-centres (or its guest twin). Keyed by addressKey with the same
  // staleness pattern.
  const [pickerOptionId, setPickerOptionId] = useState<number | string | null>(null);
  const [centres, setCentres] = useState<{
    addressKey: string; list: GigCentreOption[]; error: string | null;
  } | null>(null);

  useEffect(() => {
    if (!addressKey || pickerOptionId === null) return;
    let cancelled = false;
    (async () => {
      try {
        const res = guestAddress
          ? await fetch("/api/checkout/guest-gig-centres", {
              method: "POST",
              headers: { "content-type": "application/json" },
              body: JSON.stringify({ cart_id: cartId, address: guestAddress }),
            })
          : await fetch(`/api/checkout/gig-centres?address_id=${addressId}`);
        const data = await res.json().catch(() => null);
        if (cancelled) return;
        if (!res.ok || !Array.isArray(data)) {
          setCentres({ addressKey, list: [], error: "Couldn't load pickup centres — please try again." });
          return;
        }
        setCentres({ addressKey, list: data as GigCentreOption[], error: null });
      } catch {
        if (cancelled) return;
        setCentres({ addressKey, list: [], error: "Couldn't load pickup centres — please try again." });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [addressKey, addressId, guestAddress, cartId, pickerOptionId]);

  useEffect(() => {
    if (!addressKey || !cartId) return;
    let cancelled = false;
    (async () => {
      try {
        const res = guestAddress
          ? await fetch("/api/checkout/guest-delivery-options", {
              method: "POST",
              headers: { "content-type": "application/json" },
              body: JSON.stringify({ cart_id: cartId, address: guestAddress }),
            })
          : await fetch(
              `/api/checkout/delivery-options?address_id=${addressId}&cart_id=${encodeURIComponent(cartId)}`
            );
        const data = await res.json().catch(() => null);
        if (cancelled) return;
        if (!res.ok || !Array.isArray(data)) {
          setResult({ addressKey, cartId, options: [], error: "Couldn't load delivery options — please try again." });
          return;
        }
        setResult({ addressKey, cartId, options: data as DeliveryOption[], error: null });
      } catch {
        if (cancelled) return;
        setResult({ addressKey, cartId, options: [], error: "Couldn't load delivery options — please try again." });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [addressKey, addressId, guestAddress, cartId]);

  const stale = !result || result.addressKey !== addressKey || result.cartId !== cartId;
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
      : formatMoney(option.price, cart.currency);
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

  if (!addressKey) {
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
              : formatMoney(option.price as string, cart.currency);
            const etaLabel =
              option.min_days === option.max_days
                ? `${option.min_days} days`
                : `${option.min_days}–${option.max_days} days`;
            const centreList = centres && centres.addressKey === addressKey ? centres : null;
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
                  {option.areas_covered && (
                    <span className="mt-1 block text-muted">
                      Areas covered: {option.areas_covered}
                    </span>
                  )}
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
