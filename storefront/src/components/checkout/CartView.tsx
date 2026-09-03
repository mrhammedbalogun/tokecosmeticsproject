"use client";
import { useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { useCart } from "@/hooks/useCart";
import { mediaUrl } from "@/lib/media";
import { formatMoney } from "@/lib/country";
import { couponMessage } from "@/lib/coupon-messages";
import { COUPON_STORAGE_KEY } from "@/lib/coupon-storage";
import { ReferralCodeField } from "@/components/checkout/ReferralCodeField";
import { OrderSummary } from "@/components/checkout/OrderSummary";
import { CartComboCard } from "@/components/checkout/CartComboCard";
import type { Totals } from "@/lib/checkout";


type QuoteState =
  | { status: "idle" }
  | { status: "ok"; totals: Totals }
  | { status: "guest" }
  | { status: "invalid"; code: string }
  | { status: "error" };

/** Client cart page. Subtotal always comes from useCart() (works for guests too).
 * Full totals + coupon validation are authoritative from the server-side quote
 * endpoint, which is authed-only. There is deliberately NO background/mount-time
 * quote call — everyone (guest or authed) sees a clean subtotal-only OrderSummary
 * by default ("Delivery & taxes calculated at checkout."); the quote endpoint is
 * only ever hit from an explicit Apply-coupon click. That avoids a race between a
 * silent mount fetch and the user's own action, and means a guest never sees a
 * coupon error/note before they've touched the field. */
export function CartView() {
  const { cart, isLoading, setQty, setComboQty } = useCart();
  const [quote, setQuote] = useState<QuoteState>({ status: "idle" });
  const [applying, setApplying] = useState(false);
  const [couponInput, setCouponInput] = useState("");

  // A quantity change or removal can invalidate an already-applied coupon's totals
  // (different subtotal, maybe a min-spend no longer met) — drop back to
  // subtotal-only rather than risk showing a stale Total next to a live Subtotal.
  // The shopper can re-Apply to recompute the discount.
  function changeQty(variantId: number, quantity: number) {
    setQty.mutate({ variantId, quantity });
    setQuote({ status: "idle" });
  }

  /** Same rule for a bundle: resizing one changes the subtotal AND the combo saving, so
   *  an applied coupon's totals stop being the truth. Drop back to subtotal-only rather
   *  than show a stale Total beside a live Subtotal. */
  function changeComboQty(groupId: number, quantity: number) {
    setComboQty.mutate({ groupId, quantity });
    setQuote({ status: "idle" });
  }

  /** Re-quote after a referral code is applied, so the customer's discount appears on
   *  the summary instead of being promised and then not shown.
   *
   *  Reuses the coupon path with whatever code is (or is not) in the box — the quote
   *  endpoint takes both and the BFF supplies the referral cookie either way. It does not
   *  break this page's rule that the quote is hit only on an explicit click: applying a
   *  referral code IS one. */
  function requoteAfterReferral() {
    if (!cart.id) return;
    void applyCoupon({ allowEmptyCode: true });
  }

  async function applyCoupon({ allowEmptyCode = false } = {}) {
    const code = couponInput.trim();
    if ((!code && !allowEmptyCode) || !cart.id) return;
    setApplying(true);
    try {
      const res = await fetch("/api/checkout/quote", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ cart_id: cart.id, coupon_code: code }),
      });
      // With no coupon typed, this quote was triggered by a REFERRAL code, and every
      // failure message below is about coupons. Saying "sign in to use a coupon" to
      // somebody who just entered a friend's referral code is worse than saying nothing,
      // so a failed referral re-quote leaves the summary exactly as it found it — which
      // is the subtotal-only view this page shows by default anyway.
      if (res.status === 401) {
        if (code) {
          sessionStorage.setItem(COUPON_STORAGE_KEY, code);
          setQuote({ status: "guest" });
        }
        return;
      }
      if (!res.ok) {
        if (code) setQuote({ status: "error" });
        return;
      }
      const data = await res.json();
      if (data.coupon?.ok || !code) {
        // `!code` also lands here on a coupon verdict of "not ok", which is not a verdict
        // on anything the shopper did — there was no coupon. The totals are still good
        // and they carry the referral discount, so show them.
        setQuote({ status: "ok", totals: data.totals });
      } else {
        setQuote({ status: "invalid", code: data.coupon?.error_code ?? "" });
      }
    } catch {
      if (code) setQuote({ status: "error" });
    } finally {
      setApplying(false);
    }
  }

  if (isLoading) {
    return <p className="mt-8 text-muted">Loading your cart…</p>;
  }

  const combos = cart.combos ?? [];

  if (cart.items.length === 0 && combos.length === 0) {
    return (
      <div className="mt-10 rounded-[var(--radius-card)] border border-line bg-surface p-10 text-center">
        <p className="text-muted">Your cart is empty.</p>
        <Link
          href="/products"
          className="mt-4 inline-block rounded-[var(--radius-card)] bg-accent px-6 py-3 text-surface transition-colors hover:bg-accent-strong"
        >
          Continue shopping
        </Link>
      </div>
    );
  }

  const totals = quote.status === "ok" ? quote.totals : null;

  return (
    <div className="mt-8 grid gap-8 lg:grid-cols-3">
      <div className="lg:col-span-2 space-y-4">
        {combos.map((combo) => (
          <CartComboCard
            key={combo.group_id}
            combo={combo}
            currency={cart.currency}
            onQuantity={(quantity) => changeComboQty(combo.group_id, quantity)}
          />
        ))}
        {cart.items.map((line) => (
          <div
            key={line.id}
            className={`flex items-center justify-between gap-4 rounded-[var(--radius-card)] border border-line bg-surface p-4 ${line.unavailable ? "opacity-60" : ""}`}
          >
            <div className="flex min-w-0 items-center gap-4">
              {/* Same 80px square as the cart drawer, so the two views of one cart
                  agree. bg-beige stands in for products with no photograph. */}
              <div aria-hidden className="relative hidden h-20 w-20 shrink-0 overflow-hidden rounded-[10px] border border-line bg-beige sm:block">
                {(() => {
                  const img = mediaUrl(line.image);
                  return img ? (
                    <Image src={img} alt="" fill sizes="80px" className="object-cover" />
                  ) : null;
                })()}
              </div>
              <div className="min-w-0">
              <p className="font-medium">
                {line.product_slug ? (
                  <Link href={`/product/${line.product_slug}`} className="hover:text-accent">{line.name}</Link>
                ) : (
                  line.name
                )}
              </p>
              {line.unavailable ? (
                <p className="text-sm text-accent">No longer available</p>
              ) : (
                <p className="text-sm text-muted">
                  {line.unit_price ? formatMoney(line.unit_price, cart.currency) : "—"} each
                </p>
              )}
              </div>
            </div>
            <div className="flex items-center gap-4">
              {!line.unavailable && (
                <div className="flex items-center gap-2" role="group" aria-label={`Quantity for ${line.name}`}>
                  <button
                    type="button"
                    aria-label={`Decrease quantity of ${line.name}`}
                    onClick={() => changeQty(line.variant_id, Math.max(0, line.quantity - 1))}
                    className="h-8 w-8 rounded-full border border-line text-muted hover:text-foreground"
                  >
                    −
                  </button>
                  <span aria-live="polite">{line.quantity}</span>
                  <button
                    type="button"
                    aria-label={`Increase quantity of ${line.name}`}
                    onClick={() => changeQty(line.variant_id, line.quantity + 1)}
                    className="h-8 w-8 rounded-full border border-line text-muted hover:text-foreground"
                  >
                    +
                  </button>
                </div>
              )}
              <span className="w-20 text-right font-medium">
                {line.line_total ? formatMoney(line.line_total, cart.currency) : "—"}
              </span>
              <button
                type="button"
                aria-label={`Remove ${line.name}`}
                onClick={() => changeQty(line.variant_id, 0)}
                className="text-muted hover:text-foreground"
              >
                ×
              </button>
            </div>
          </div>
        ))}
      </div>

      <div className="space-y-4">
        <div className="rounded-[var(--radius-card)] border border-line bg-surface p-5">
          <label htmlFor="coupon-code" className="mb-2 block text-sm font-medium">
            Coupon code
          </label>
          <div className="flex gap-2">
            <input
              id="coupon-code"
              type="text"
              value={couponInput}
              onChange={(e) => setCouponInput(e.target.value)}
              placeholder="Enter code"
              className="min-w-0 flex-1 rounded-[var(--radius-card)] border border-line bg-beige px-3 py-2 text-sm"
            />
            <button
              type="button"
              onClick={() => void applyCoupon()}
              disabled={!couponInput.trim() || applying}
              className="rounded-[var(--radius-card)] bg-accent px-4 py-2 text-sm text-surface transition-colors hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-60"
            >
              Apply
            </button>
          </div>
          <p aria-live="polite" className="mt-2 text-sm">
            {quote.status === "invalid" && (
              <span className="text-accent">{couponMessage(quote.code)}</span>
            )}
            {quote.status === "guest" && (
              <span className="text-muted">You can apply your code at checkout.</span>
            )}
            {quote.status === "error" && (
              <span className="text-muted">We couldn&apos;t apply that code — please try again.</span>
            )}
          </p>
        </div>

        {/* Under the coupon box, collapsed. A referral code is the same SHAPE of thing
            to a shopper ("I was given a code") so it belongs here, and since 2026-08-27
            it does move the price too — the referred customer takes a percentage off.
            It keeps its own component and wording anyway: only this one can be refused
            for being your own code, and only this one pays somebody. */}
        <ReferralCodeField onApplied={requoteAfterReferral} />

        <div className="rounded-[var(--radius-card)] border border-line bg-surface p-5">
          {/* `cart.total` is the goods net of any bundle saving — the same figure the
              quote's `subtotal - combo_discount` produces, so the fallback and the real
              summary agree. `fallbackComboSaving` is what draws the saving row before a
              quote exists (a guest never gets one: the quote endpoint is authed-only). */}
          <OrderSummary
            totals={totals}
            fallbackSubtotal={cart.subtotal}
            fallbackComboSaving={cart.combo_discount}
            fallbackTotal={cart.total}
            currency={cart.currency}
          />
        </div>

        <p className="text-center text-xs text-muted">Secure checkout</p>

        <Link
          href="/checkout"
          className="block rounded-[var(--radius-card)] bg-accent py-3 text-center text-surface transition-colors hover:bg-accent-strong"
        >
          Proceed to checkout
        </Link>
      </div>
    </div>
  );
}
