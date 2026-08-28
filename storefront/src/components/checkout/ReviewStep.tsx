"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCheckout } from "@/components/checkout/CheckoutContext";
import { useCart } from "@/hooks/useCart";
import { formatMoney } from "@/lib/country";
import { OrderSummary } from "@/components/checkout/OrderSummary";
import { ReferralCodeField } from "@/components/checkout/ReferralCodeField";
import { couponMessage } from "@/lib/coupon-messages";
import { paymentLabel } from "@/lib/payment-labels";
import { stashBankHandoff } from "@/lib/bank-handoff";
import { COUPON_STORAGE_KEY } from "@/lib/coupon-storage";
import { PaymentLauncher, type LaunchInfo } from "@/components/checkout/PaymentLauncher";
import { TurnstileWidget, turnstileToken } from "@/components/auth/TurnstileWidget";
import type { Totals } from "@/lib/checkout";


/** Real CheckoutError codes from backend/apps/checkout/services/checkout.py, mapped to
 * shopper-facing copy. `cartLink` codes get a "Review your cart" link back to /cart;
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
    return { message: "Some items in your cart are no longer available in that quantity.", cartLink: true };
  }
  if (code === "cart_changed") {
    return { message: "Prices changed since you started checkout — please review your cart.", cartLink: true };
  }
  if (code === "cart_not_active" || code === "cart_empty") {
    return { message: "Your cart has changed — please review it before continuing.", cartLink: true };
  }
  if (code === "delivery_option_invalid") {
    return { message: "That delivery option is no longer valid for this address — please choose again.", cartLink: false };
  }
  if (code === "centre_required" || code === "centre_invalid") {
    return { message: "Please choose a pickup centre for this delivery option.", cartLink: false };
  }
  if (code === "store_required" || code === "store_invalid") {
    return { message: "Please choose a store for this pickup option.", cartLink: false };
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
  addressKey: string;
  deliveryOptionId: number | string;
  gigCentreId?: number;
  couponCode: string;
  /** Which referral state this result was fetched under. Part of the key, not just an
   *  effect dependency, so the totals go STALE the instant a code is applied. Without it
   *  the old grand_total stays on screen — and stays sendable as `expected_total` — until
   *  the new quote lands, and a place-order in that window is refused as `cart_changed`.
   *  Safe, but a confusing refusal where a disabled button is the honest answer. */
  referralNonce: number;
  totals: Totals | null;
  couponError: string | null;
  error: string | null;
}

/** Step 5 of checkout: review + idempotent place-order (Plan-14 Task 10). This is the
 * money-critical step — the grand total shown and sent as `expected_total` is ALWAYS
 * the server's authoritative quote, never computed here.
 *
 * Double-submit / lost-response safety has two layers:
 *  1. The common case (an impatient double-click) is caught client-side by the
 *     `placing` disable below.
 *  2. The dangerous case is a network blip that loses the 201 response AFTER the
 *     backend already created the order (cart converted, stock reserved) — the
 *     button re-enables on any fetch error, so the shopper naturally retries. That
 *     retry MUST reuse the exact same Idempotency-Key as the original attempt: the
 *     backend's idempotency layer (begin()/finish() in idempotency.py) replays the
 *     STORED 201 — bank details included — for a same-key retry, but a fresh key
 *     would hit the now-converted cart and return a spurious cart_not_active,
 *     orphaning a real pending order with its bank details never shown. `idemKeyRef`
 *     is minted once per mount (one key per checkout attempt) and never regenerated,
 *     so every Place-order click from this component — first try or retry — carries
 *     the same key through to the BFF (`route.ts`), which forwards it as the header. */
export function ReviewStep() {
  const { selections, setSelection } = useCheckout();
  const { cart } = useCart();
  const router = useRouter();

  const addressId = selections.addressId;
  // Guest checkout (Plan-38): the inline address payload replaces addressId, the
  // contact rides the placement body, and the Place-order button is Turnstile-gated.
  const guest = selections.guest;
  const guestAddress = guest ? selections.guestAddress : undefined;
  const deliveryOptionId = selections.deliveryOptionId;
  const gigCentreId = selections.gigCentreId;
  const cartId = cart.id;
  const addressKey = guestAddress ? JSON.stringify(guestAddress) : addressId ? String(addressId) : "";
  // Counts completed place attempts — the Turnstile reset signal (tokens are
  // single-use, so every finished attempt must hand the guest a fresh one; the
  // backend answers a true same-key replay from its store without re-checking).
  const [attempts, setAttempts] = useState(0);

  // Lazy useState initializer — computed exactly once on mount, stable for the
  // component's lifetime (nothing ever calls the setter again). Deliberately NOT a
  // ref: eslint's react-hooks/refs rule flags reading `ref.current` during render
  // even for the standard lazy-ref-init pattern, so useState is the clean way to get
  // a mount-once, render-stable value here.
  const [idemKey] = useState<string>(() => crypto.randomUUID());

  // Pre-fill from the guest coupon-code stash (read once at mount via lazy init —
  // not an effect, so it can't trip react-hooks/set-state-in-effect). `appliedCoupon`
  // is the code the quote below is/was fetched for; it only changes when Apply is
  // clicked, which is what re-triggers the quote effect.
  const [couponInput, setCouponInput] = useState(() =>
    typeof sessionStorage === "undefined" ? "" : sessionStorage.getItem(COUPON_STORAGE_KEY) ?? ""
  );
  const [appliedCoupon, setAppliedCoupon] = useState(couponInput);

  // Bumped when a referral code is applied, to re-run the quote below. A counter rather
  // than the code itself: the code never reaches this component — it goes into an
  // httpOnly cookie the BFF reads — so all this side knows, and all it needs to know, is
  // that the server's answer has changed. Since 2026-08-27 an attributed order discounts
  // the customer's own goods, so the quote genuinely does move.
  const [referralNonce, setReferralNonce] = useState(0);

  // Keyed-result pattern (mirrors DeliveryStep/PaymentStep): the effect never resets
  // state synchronously on a dependency change; staleness is derived at render time
  // by comparing the result's key to the current inputs, and `cancelled` stops a
  // superseded slow response from landing.
  const [result, setResult] = useState<QuoteFetchResult | null>(null);

  useEffect(() => {
    if (!cartId || !addressKey || !deliveryOptionId) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/checkout/quote", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            cart_id: cartId,
            // Saved-address id for the authed flow; inline payload + contact details
            // for guests (the BFF routes to the guest quote endpoint, which threads the
            // email into the per-email coupon checks).
            //
            // The PHONE goes too, since 2026-08-28, and only for the self-referral
            // guard: a guest is identified to the referral programme by these two
            // fields, and if the preview cannot see them it will quote a 5% discount
            // that `place_order` then refuses — turning the pay button into a
            // `cart_changed` error instead of showing the truth on this screen.
            ...(guestAddress
              ? {
                  address: guestAddress,
                  guest_email: guest?.email ?? "",
                  guest_phone: guest?.phone ?? "",
                }
              : { address_id: addressId }),
            delivery_option_id: deliveryOptionId,
            gig_centre_id: gigCentreId,
            coupon_code: appliedCoupon,
          }),
        });
        const data = await res.json().catch(() => null);
        if (cancelled) return;
        if (!res.ok || !data?.totals) {
          setResult({
            cartId, addressKey, deliveryOptionId, gigCentreId, couponCode: appliedCoupon,
            referralNonce,
            totals: null, couponError: null,
            error: "Couldn't load your order total — please try again.",
          });
          return;
        }
        const couponError = appliedCoupon && !data.coupon?.ok ? data.coupon?.error_code ?? "" : null;
        setResult({
          cartId, addressKey, deliveryOptionId, gigCentreId, couponCode: appliedCoupon,
          referralNonce,
          totals: data.totals as Totals, couponError, error: null,
        });
      } catch {
        if (cancelled) return;
        setResult({
          cartId, addressKey, deliveryOptionId, gigCentreId, couponCode: appliedCoupon,
          referralNonce,
          totals: null, couponError: null,
          error: "Couldn't load your order total — please try again.",
        });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [cartId, addressKey, addressId, guestAddress, guest, deliveryOptionId, gigCentreId,
      appliedCoupon, referralNonce]);

  const stale =
    !result ||
    result.cartId !== cartId ||
    result.addressKey !== addressKey ||
    result.deliveryOptionId !== deliveryOptionId ||
    result.gigCentreId !== gigCentreId ||
    result.couponCode !== appliedCoupon ||
    result.referralNonce !== referralNonce;
  const totals = stale ? null : result.totals;
  const quoteError = stale ? null : result.error;
  const couponError = stale ? null : result.couponError;

  const [placing, setPlacing] = useState(false);
  const [placeError, setPlaceError] = useState<{ message: string; cartLink: boolean } | null>(null);
  // Set once the order is placed with an ONLINE gateway: the review UI gives way to the
  // launcher, which collects the money and routes onward.
  const [launch, setLaunch] = useState<LaunchInfo | null>(null);

  function applyCoupon() {
    setAppliedCoupon(couponInput.trim());
  }

  async function handlePlaceOrder() {
    if (!totals || !cartId || !addressKey || !deliveryOptionId || !selections.paymentGateway || placing) return;
    setPlacing(true);
    setPlaceError(null);
    try {
      // The widget token is read at CLICK time, not render time — a shopper who
      // dwells on Review past the ~5-minute token validity gets whatever the
      // widget currently holds (it refreshes itself).
      const tsToken = guest ? turnstileToken() : undefined;
      const res = await fetch("/api/checkout", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          cart_id: cartId,
          ...(guestAddress
            ? {
                address: guestAddress,
                guest_email: guest?.email ?? "",
                guest_phone: guest?.phone ?? "",
                ...(tsToken ? { turnstile_token: tsToken } : {}),
              }
            : { address_id: addressId }),
          delivery_option_id: deliveryOptionId,
          gig_centre_id: gigCentreId,
          pickup_store_id: selections.pickupStoreId,
          payment_gateway: selections.paymentGateway,
          coupon_code: appliedCoupon,
          notes: selections.note,
          expected_total: totals.grand_total,
          idempotency_key: idemKey,
        }),
      });
      const data = await res.json().catch(() => null);
      if (res.status === 201 && data?.order_number) {
        // Guest coupon stash has done its job (pre-filled + applied) — clear it so a
        // later cart/checkout doesn't silently re-apply a code from a finished order.
        if (typeof sessionStorage !== "undefined") sessionStorage.removeItem(COUPON_STORAGE_KEY);
        const payment = data.payment ?? {};
        if (payment.action === "bank_details") {
          if (payment.data) stashBankHandoff(data.order_number, payment.data);
          router.push(`/checkout/confirmation/${data.order_number}`);
          return;
        }
        // Online gateway: hand off to the launcher (inline pop-up / redirect), which
        // owns verify + routing to confirmation from here. Deliberately NOT stashed as
        // a bank handoff — payment.data here is SDK material (access_code / order_id),
        // and stashing it would show bank instructions for a card order.
        setLaunch({
          gateway: payment.gateway,
          reference: payment.reference,
          orderNumber: data.order_number,
          data: payment.data ?? {},
        });
        return;
      }
      setPlaceError(mapPlaceOrderError(data));
    } catch {
      setPlaceError({ message: "Something went wrong placing your order — please try again.", cartLink: false });
    } finally {
      setPlacing(false);
      // Every completed attempt spends the widget token — reset for a fresh one so
      // a retry (gateway down, stock change) is not refused as a duplicate solve.
      setAttempts((a) => a + 1);
    }
  }

  if (!addressKey || !deliveryOptionId || !selections.paymentGateway) {
    return <p className="text-sm text-muted">Complete the previous steps first.</p>;
  }

  // The order exists and is awaiting money — show only the payment step, so nothing on
  // screen invites re-placing an order that has already been created.
  if (launch) {
    return (
      <div className="space-y-4">
        <PaymentLauncher launch={launch} />
      </div>
    );
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
                {line.unit_price ? ` · ${formatMoney(line.unit_price, cart.currency)} each` : ""}
              </p>
            </div>
            <span className="font-medium">
              {line.line_total ? formatMoney(line.line_total, cart.currency) : "—"}
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

      {/* Under the coupon, same as on the cart page, and for the same reason: to a
          shopper both are "a code I was given", so they belong next to each other. They
          keep separate components and wording because only one of them can be refused for
          being your own code, and only one of them pays somebody.

          This is the LAST point at which attribution can still be claimed, and for
          anyone who arrived via "Buy now" or the cart drawer it is the ONLY one — those
          two routes never render /cart.

          IT NOW RE-QUOTES. Until 2026-08-27 applying here changed nothing in `totals`,
          so the field could fire and forget. The referred customer's discount changed
          that: the code still only reaches the server as an httpOnly cookie, but the
          quote reads that cookie, so the totals on screen are stale the moment a code is
          accepted. `referralNonce` is what re-runs the effect. */}
      <div className="border-t border-line pt-4">
        <ReferralCodeField
          variant="inline"
          onApplied={() => setReferralNonce((n) => n + 1)}
        />
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
            <Link href="/cart" className="underline">
              Review your cart
            </Link>
          )}
        </p>
      )}

      {/* Guests are bot-gated at the one write that reserves stock and sends mail.
          Renders nothing while the gate is off (no NEXT_PUBLIC_TURNSTILE_SITE_KEY),
          matching every other Turnstile surface. */}
      {guest && <TurnstileWidget resetSignal={attempts} />}

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
