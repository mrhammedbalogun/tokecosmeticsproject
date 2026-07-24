"use client";
import { useState } from "react";
import Link from "next/link";
import { useCart } from "@/hooks/useCart";
import { formatMoney } from "@/lib/country";
import { couponMessage } from "@/lib/coupon-messages";
import { OrderSummary } from "@/components/checkout/OrderSummary";
import type { Totals } from "@/lib/checkout";

const COUPON_STORAGE_KEY = "toke-coupon-code";

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
  const { cart, isLoading, setQty } = useCart();
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

  async function applyCoupon() {
    const code = couponInput.trim();
    if (!code || !cart.id) return;
    setApplying(true);
    try {
      const res = await fetch("/api/checkout/quote", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ cart_id: cart.id, coupon_code: code }),
      });
      if (res.status === 401) {
        sessionStorage.setItem(COUPON_STORAGE_KEY, code);
        setQuote({ status: "guest" });
        return;
      }
      if (!res.ok) {
        setQuote({ status: "error" });
        return;
      }
      const data = await res.json();
      if (data.coupon?.ok) {
        setQuote({ status: "ok", totals: data.totals });
      } else {
        setQuote({ status: "invalid", code: data.coupon?.error_code ?? "" });
      }
    } catch {
      setQuote({ status: "error" });
    } finally {
      setApplying(false);
    }
  }

  if (isLoading) {
    return <p className="mt-8 text-muted">Loading your bag…</p>;
  }

  if (cart.items.length === 0) {
    return (
      <div className="mt-10 rounded-[var(--radius-card)] border border-line bg-surface p-10 text-center">
        <p className="text-muted">Your bag is empty.</p>
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
        {cart.items.map((line) => (
          <div
            key={line.id}
            className={`flex items-center justify-between gap-4 rounded-[var(--radius-card)] border border-line bg-surface p-4 ${line.unavailable ? "opacity-60" : ""}`}
          >
            <div>
              <p className="font-medium">{line.name}</p>
              {line.unavailable ? (
                <p className="text-sm text-accent">No longer available</p>
              ) : (
                <p className="text-sm text-muted">
                  {line.unit_price ? formatMoney(line.unit_price, cart.currency, "") : "—"} each
                </p>
              )}
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
                {line.line_total ? formatMoney(line.line_total, cart.currency, "") : "—"}
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
              onClick={applyCoupon}
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

        <div className="rounded-[var(--radius-card)] border border-line bg-surface p-5">
          <OrderSummary totals={totals} fallbackSubtotal={cart.subtotal} currency={cart.currency} />
        </div>

        <p className="text-center text-xs text-muted">Secure checkout · 14-day returns</p>

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
