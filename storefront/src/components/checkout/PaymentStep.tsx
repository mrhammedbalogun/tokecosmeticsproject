"use client";
import { useEffect, useState } from "react";
import { useCheckout } from "@/components/checkout/CheckoutContext";
import { useCart } from "@/hooks/useCart";
import { paymentLabel } from "@/lib/payment-labels";
import type { PaymentMethod } from "@/lib/checkout";

/** Step 4 of checkout: the payment-method chooser (Plan-14 Task 9).
 *
 * - Fetches `/api/checkout/payment-methods?country=<CC>` whenever `cart.country`
 *   changes, mirroring DeliveryStep's keyed-result / staleness-derived-at-render
 *   pattern — no synchronous setState in the effect body; the "last fetched for"
 *   country is compared against the current country at render time instead.
 * - Only bank_transfer is active today; the rest of the gateways come in Plan-14b.
 *   Whatever the API returns renders via `paymentLabel`, so new gateways appear
 *   automatically with no rework here.
 * - The lowest-sort_order method (API already sorts) is preselected *visually* —
 *   derived at render time from `selections.paymentGateway ?? methods[0].gateway`,
 *   no extra state — so today's bank-transfer-only case is a single click. Nothing
 *   auto-completes the step; the shopper must click, same as AddressStep/DeliveryStep.
 */
interface FetchResult {
  country: string;
  methods: PaymentMethod[];
  error: string | null;
}

export function PaymentStep() {
  const { selections, complete } = useCheckout();
  const { cart } = useCart();
  const country = cart.country;

  const [result, setResult] = useState<FetchResult | null>(null);

  useEffect(() => {
    if (!country) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`/api/checkout/payment-methods?country=${encodeURIComponent(country)}`);
        const data = await res.json().catch(() => null);
        if (cancelled) return;
        if (!res.ok || !Array.isArray(data)) {
          setResult({ country, methods: [], error: "Couldn't load payment methods — please try again." });
          return;
        }
        setResult({ country, methods: data as PaymentMethod[], error: null });
      } catch {
        if (cancelled) return;
        setResult({ country, methods: [], error: "Couldn't load payment methods — please try again." });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [country]);

  const stale = !result || result.country !== country;
  const methods = stale ? null : result.methods;
  const error = stale ? null : result.error;

  function handleSelect(gateway: string) {
    complete(4, { paymentGateway: gateway });
  }

  if (!country) {
    return <p className="text-sm text-muted">Loading…</p>;
  }

  if (methods === null) {
    return <p className="text-sm text-muted">Loading payment methods…</p>;
  }

  const visualGateway = selections.paymentGateway ?? methods[0]?.gateway;

  return (
    <div className="space-y-3">
      {error && (
        <p role="alert" className="text-sm text-red-700">
          {error}
        </p>
      )}

      {!error && methods.length === 0 && (
        <p className="text-sm text-muted">
          No payment methods available for your region — please contact us.
        </p>
      )}

      {methods.length > 0 && (
        <div role="radiogroup" aria-label="Payment methods" className="space-y-3">
          {methods.map((method) => {
            const checked = visualGateway === method.gateway;
            const label = paymentLabel(method.gateway);
            return (
              <button
                key={method.gateway}
                type="button"
                role="radio"
                aria-checked={checked}
                onClick={() => handleSelect(method.gateway)}
                className={`block w-full rounded-[var(--radius-card)] border p-4 text-left text-sm transition-colors ${
                  checked ? "border-accent bg-accent/5" : "border-line hover:border-accent/60"
                }`}
              >
                <span className="font-medium">{label.name}</span>
                {label.note && <span className="mt-1 block text-muted">{label.note}</span>}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
