"use client";
import { useEffect, useState } from "react";
import { useCheckout } from "@/components/checkout/CheckoutContext";
import { OverlayPortal } from "@/components/layout/OverlayPortal";
import { useCart } from "@/hooks/useCart";
import { paymentLabel } from "@/lib/payment-labels";
import type { PaymentMethod } from "@/lib/checkout";

/** The market's payment instructions (admin-authored, nh3-sanitised HTML) in a modal —
 * the method card offers them behind a "Read payment instructions" link instead of
 * dumping a wall of policy text into the chooser. */
function InstructionsModal({
  title,
  html,
  onClose,
}: {
  title: string;
  html: string;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <OverlayPortal>
      <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/30 sm:items-center sm:p-6">
        <button aria-label="Close" tabIndex={-1} onClick={onClose} className="absolute inset-0 cursor-default" />
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="payment-instructions-title"
          className="relative flex max-h-[85vh] w-full flex-col rounded-t-2xl bg-surface shadow-2xl sm:max-w-lg sm:rounded-2xl"
        >
          <div className="flex items-center justify-between border-b border-line px-6 py-4">
            <h2 id="payment-instructions-title" className="font-display text-lg">
              {title}
            </h2>
            <button
              onClick={onClose}
              aria-label="Close"
              className="text-muted transition-colors hover:text-foreground"
            >
              ✕
            </button>
          </div>
          <div
            className="rich-text overflow-y-auto px-6 py-4 text-sm leading-relaxed"
            // Sanitised on the backend on write (nh3 allow-list, apps/cms/sanitize.py)
            // — same contract as the product prose fields.
            dangerouslySetInnerHTML={{ __html: html }}
          />
        </div>
      </div>
    </OverlayPortal>
  );
}

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
  const [reading, setReading] = useState<PaymentMethod | null>(null);

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
            const hasInstructions = Boolean(method.instructions?.trim());
            // The selectable area and the read-instructions link are SIBLINGS inside
            // the bordered card — a button cannot legally nest another button, and the
            // link must not also select the method.
            return (
              <div
                key={method.gateway}
                className={`rounded-[var(--radius-card)] border text-sm transition-colors ${
                  checked ? "border-accent bg-accent/5" : "border-line hover:border-accent/60"
                }`}
              >
                <button
                  type="button"
                  role="radio"
                  aria-checked={checked}
                  onClick={() => handleSelect(method.gateway)}
                  className="block w-full p-4 text-left"
                >
                  <span className="font-medium">{label.name}</span>
                  {label.note && <span className="mt-1 block text-muted">{label.note}</span>}
                </button>
                {hasInstructions && (
                  <button
                    type="button"
                    onClick={() => setReading(method)}
                    className="block px-4 pb-3 text-xs font-medium text-accent underline underline-offset-2 hover:text-accent-strong"
                  >
                    Read payment instructions
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}

      {reading?.instructions && (
        <InstructionsModal
          title={`${paymentLabel(reading.gateway).name} — payment instructions`}
          html={reading.instructions}
          onClose={() => setReading(null)}
        />
      )}
    </div>
  );
}
