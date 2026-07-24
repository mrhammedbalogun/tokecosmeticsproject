"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useCheckout } from "@/components/checkout/CheckoutContext";
import { useCart } from "@/hooks/useCart";
import { formatMoney } from "@/lib/country";
import { OrderSummary } from "@/components/checkout/OrderSummary";
import { couponMessage } from "@/lib/coupon-messages";
import { paymentLabel } from "@/lib/payment-labels";
import { stashBankHandoff } from "@/lib/bank-handoff";
import type { Totals } from "@/lib/checkout";

// Matches CartView's sessionStorage key for a guest's applied coupon — not exported
// from there, so the literal is duplicated here (see CartView.tsx's COUPON_STORAGE_KEY).
const COUPON_STORAGE_KEY = "toke-coupon-code";

/** Real CheckoutError codes from backend/apps/checkout/services/checkout.py, mapped to
 * shopper-facing copy. `cartLink` codes get a "Review your bag" link back to /cart;
 * there is no "reservation_expired" code — reservation only exists for an order that
 * already placed, not for placement itself, so that scenario from the task brief
 * doesn't apply here (see the final report for this note). */
function mapPlaceOrderError(data: { error?: string; detail?: string } | null): {
  message: string;
  cartLink: boolean;
} {
  if (!data?.error) {
    return { message: data?.detail || "Something went wrong placing your order — please try again.", cartLink: false };
  }
  const code = data.error;
  if (code === "idempotency_in_progress") {
    return { message: "Still finishing your previous attempt — one moment, then try again.", cartLink: false };
  }
  if (code.startsWith("coupon_")) {
    return { message: couponMessage(code.slice("coupon_".length)), cartLink: false };
  }
  if (code === "insufficient_stock" || code === "line_unavailable") {
    return { message: "Some items in your bag are no longer available in that quantity.", cartLink: true };
  }
  if (code === "cart_changed") {
    return { message: "Prices changed since you started checkout — please review your bag.", cartLink: true };
  }
  if (code === "cart_not_active" || code === "cart_empty") {
    return { message: "Your bag has changed — please review it before continuing.", cartLink: true };
  }
  if (code === "delivery_option_invalid") {
    return { message: "That delivery option is no longer valid for this address — please choose again.", cartLink: false };
  }
  if (code === "address_invalid") {
    return { message: "That address is no longer valid — please choose or add another.", cartLink: false };
  }
  if (code === "gateway_unavailable" || code === "gateway_not_configured") {
    return { message: "That payment method isn't available right now — please choose another.", cartLink: false };
  }
  if (code === "gateway_error") {
    return { message: "Payment provider is temporarily unavailable — please retry.", cartLink: false };
  }
  return { message: data.detail || "Something went wrong placing your order — please try again.", cartLink: false };
}

interface QuoteFetchResult {
  cartId: string;
  addressId: number;
  deliveryOptionId: number;
  couponCode: string;
  totals: Totals | null;
  couponError: string | null;
  error: string | null;
}

/** Step 5 of checkout: review + idempotent place-order (Plan-14 Task 10). This is the
 * money-critical step — the grand total shown and sent as `expected_total` is ALWAYS
 * the server's authoritative quote, never computed here. Nothing is placed until the
 * shopper clicks Place order; the BFF attaches the Idempotency-Key, so a double click
 * (or a slow-network retry) can't create two orders. */
export function ReviewStep() {
  const { selections, setSelection } = useCheckout();
  const { cart } = useCart();
  const router = useRouter();

  const addressId = selections.addressId;
  const deliveryOptionId = selections.deliveryOptionId;
  const cartId = cart.id;

  // Pre-fill from the guest coupon-code stash (read once at mount via lazy init —
  // not an effect, so it can't trip react-hooks/set-state-in-effect). `appliedCoupon`
  // is the code the quote below is/was fetched for; it only changes when Apply is
  // clicked, which is what re-triggers the quote effect.
  const [couponInput, setCouponInput] = useState(() =>
    typeof sessionStorage === "undefined" ? "" : sessionStorage.getItem(COUPON_STORAGE_KEY) ?? ""
  );
  const [appliedCoupon, setAppliedCoupon] = useState(couponInput);

  // Keyed-result pattern (mirrors DeliveryStep/PaymentStep): the effect never resets
  // state synchronously on a dependency change; staleness is derived at render time
  // by comparing the result's key to the current inputs, and `cancelled` stops a
  // superseded slow response from landing.
  const [result, setResult] = useState<QuoteFetchResult | null>(null);

  useEffect(() => {
    if (!cartId || !addressId || !deliveryOptionId) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/checkout/quote", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            cart_id: cartId,
            address_id: addressId,
            delivery_option_id: deliveryOptionId,
            coupon_code: appliedCoupon,
          }),
        });
        const data = await res.json().catch(() => null);
        if (cancelled) return;
        if (!res.ok || !data?.totals) {
          setResult({
            cartId, addressId, deliveryOptionId, couponCode: appliedCoupon,
            totals: null, couponError: null,
            error: "Couldn't load your order total — please try again.",
          });
          return;
        }
        const couponError = appliedCoupon && !data.coupon?.ok ? data.coupon?.error_code ?? "" : null;
        setResult({
          cartId, addressId, deliveryOptionId, couponCode: appliedCoupon,
          totals: data.totals as Totals, couponError, error: null,
        });
      } catch {
        if (cancelled) return;
        setResult({
          cartId, addressId, deliveryOptionId, couponCode: appliedCoupon,
          totals: null, couponError: null,
          error: "Couldn't load your order total — please try again.",
        });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [cartId, addressId, deliveryOptionId, appliedCoupon]);

  const stale =
    !result ||
    result.cartId !== cartId ||
    result.addressId !== addressId ||
    result.deliveryOptionId !== deliveryOptionId ||
    result.couponCode !== appliedCoupon;
  const totals = stale ? null : result.totals;
  const quoteError = stale ? null : result.error;
  const couponError = stale ? null : result.couponError;

  const [placing, setPlacing] = useState(false);
  const [placeError, setPlaceError] = useState<{ message: string; cartLink: boolean } | null>(null);

  function applyCoupon() {
    setAppliedCoupon(couponInput.trim());
  }

  async function handlePlaceOrder() {
    if (!totals || !cartId || !addressId || !deliveryOptionId || !selections.paymentGateway || placing) return;
    setPlacing(true);
    setPlaceError(null);
    try {
      const res = await fetch("/api/checkout", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          cart_id: cartId,
          address_id: addressId,
          delivery_option_id: deliveryOptionId,
          payment_gateway: selections.paymentGateway,
          coupon_code: appliedCoupon,
          notes: selections.note,
          expected_total: totals.grand_total,
        }),
      });
      const data = await res.json().catch(() => null);
      if (res.status === 201 && data?.order_number) {
        if (data.payment?.data) stashBankHandoff(data.order_number, data.payment.data);
        // Guest coupon stash has done its job (pre-filled + applied) — clear it so a
        // later cart/checkout doesn't silently re-apply a code from a finished order.
        if (typeof sessionStorage !== "undefined") sessionStorage.removeItem(COUPON_STORAGE_KEY);
        router.push(`/checkout/confirmation/${data.order_number}`);
        return;
      }
      setPlaceError(mapPlaceOrderError(data));
    } catch {
      setPlaceError({ message: "Something went wrong placing your order — please try again.", cartLink: false });
    } finally {
      setPlacing(false);
    }
  }

  if (!addressId || !deliveryOptionId || !selections.paymentGateway) {
    return <p className="text-sm text-muted">Complete the previous steps first.</p>;
  }

  return (
    <div className="space-y-6">
      <div className="space-y-3">
        {cart.items.map((line) => (
          <div key={line.id} className="flex items-center justify-between gap-4 text-sm">
            <div>
              <p className="font-medium">{line.name}</p>
              <p className="text-muted">
                Qty {line.quantity}
                {line.unit_price ? ` · ${formatMoney(line.unit_price, cart.currency, "")} each` : ""}
              </p>
            </div>
            <span className="font-medium">
              {line.line_total ? formatMoney(line.line_total, cart.currency, "") : "—"}
            </span>
          </div>
        ))}
      </div>

      <dl className="space-y-2 border-t border-line pt-4 text-sm">
        <div className="flex justify-between gap-4">
          <dt className="text-muted">Delivery address</dt>
          <dd className="text-right">{selections.addressDisplay ?? "Selected"}</dd>
        </div>
        <div className="flex justify-between gap-4">
          <dt className="text-muted">Delivery method</dt>
          <dd className="text-right">{selections.deliveryDisplay ?? "Selected"}</dd>
        </div>
        <div className="flex justify-between gap-4">
          <dt className="text-muted">Payment method</dt>
          <dd className="text-right">{paymentLabel(selections.paymentGateway).name}</dd>
        </div>
      </dl>

      <div className="border-t border-line pt-4">
        <label htmlFor="review-coupon-code" className="mb-2 block text-sm font-medium">
          Coupon code
        </label>
        <div className="flex gap-2">
          <input
            id="review-coupon-code"
            type="text"
            value={couponInput}
            onChange={(e) => setCouponInput(e.target.value)}
            placeholder="Enter code"
            className="min-w-0 flex-1 rounded-[var(--radius-card)] border border-line bg-beige px-3 py-2 text-sm"
          />
          <button
            type="button"
            onClick={applyCoupon}
            disabled={!couponInput.trim()}
            className="rounded-[var(--radius-card)] bg-accent px-4 py-2 text-sm text-surface transition-colors hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-60"
          >
            Apply
          </button>
        </div>
        {couponError && (
          <p role="alert" className="mt-2 text-sm text-red-700">
            {couponMessage(couponError)}
          </p>
        )}
      </div>

      <div className="border-t border-line pt-4">
        <label htmlFor="review-note" className="mb-2 block text-sm font-medium">
          Order note (optional)
        </label>
        <textarea
          id="review-note"
          value={selections.note}
          onChange={(e) => setSelection({ note: e.target.value })}
          rows={3}
          className="w-full rounded-[var(--radius-card)] border border-line bg-beige px-3 py-2 text-sm"
        />
      </div>

      {quoteError && (
        <p role="alert" className="text-sm text-red-700">
          {quoteError}
        </p>
      )}

      <div className="border-t border-line pt-4">
        <OrderSummary totals={totals} fallbackSubtotal={cart.subtotal} currency={cart.currency} />
      </div>

      {placeError && (
        <p role="alert" className="text-sm text-red-700">
          {placeError.message}{" "}
          {placeError.cartLink && (
            <a href="/cart" className="underline">
              Review your bag
            </a>
          )}
        </p>
      )}

      <button
        type="button"
        onClick={handlePlaceOrder}
        disabled={!totals || placing}
        className="w-full rounded-[var(--radius-card)] bg-accent px-4 py-3 text-sm font-medium text-surface transition-colors hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-60"
      >
        {placing ? "Placing order…" : "Place order"}
      </button>
    </div>
  );
}
