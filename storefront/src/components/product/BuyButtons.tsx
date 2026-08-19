"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { isJustSoldOut, useCart } from "@/hooks/useCart";
import { openCartDrawer } from "@/lib/cart-ui";
import { usePdp } from "@/components/product/PdpContext";
import { BUYNOW_INTENT_KEY } from "@/lib/buynow-intent";

/** Amazon-pattern pair (Decision 14): Buy Now = primary (straight to checkout),
 * Add to Cart = secondary (opens the drawer). Guest Buy Now goes straight to
 * checkout too since Plan-38 (guest checkout) — the BFF adds to the guest cart, no
 * login detour. The 401→stash-intent→/login branch below is kept as a fallback for
 * an authed session that expires mid-click, not the guest path any more. */
export function BuyButtons() {
  const { variant, qty } = usePdp();
  const { addItem } = useCart();
  const queryClient = useQueryClient();
  const router = useRouter();
  const [busy, setBusy] = useState<"buy" | "add" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const disabled = !variant || !variant.in_stock || variant.price === null;

  async function addToCart() {
    if (!variant) return;
    setBusy("add"); setError(null);
    try {
      await addItem.mutateAsync({ variantId: variant.id, quantity: qty });
      openCartDrawer();
    } catch (err) {
      if (isJustSoldOut(err)) {
        setError("Just sold out — this item is no longer available.");
        router.refresh(); // re-render the PDP with its true stock state
      } else {
        setError("Could not add to cart — please try again.");
      }
    } finally { setBusy(null); }
  }

  async function buyNow() {
    if (!variant) return;
    setBusy("buy"); setError(null);
    try {
      const res = await fetch("/api/checkout/buy-now", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ variant_id: variant.id, quantity: qty }),
      });
      if (res.status === 401) {
        sessionStorage.setItem(BUYNOW_INTENT_KEY,
          JSON.stringify({ variant_id: variant.id, quantity: qty }));
        router.push("/login?next=/checkout");
        return;
      }
      if (!res.ok) {
        const body: { code?: string } | null = await res.json().catch(() => null);
        if (res.status === 409 && body?.code === "out_of_stock") {
          setError("Just sold out — this item is no longer available.");
          router.refresh();
          setBusy(null);
          return;
        }
        throw new Error();
      }
      // Buy-now returns the STANDARD cart with the item added (it is the same cart
      // checkout reads). Seed the query cache before navigating: ["cart"] is fresh
      // for 30s, so without this checkout would trust a stale empty cart and render
      // "Your cart is empty" — the shipped bug that retired the express cart.
      queryClient.setQueryData(["cart"], await res.json());
      router.push("/checkout");
    } catch {
      setError("Buy Now is unavailable right now — try Add to Cart.");
      setBusy(null);
    }
  }

  return (
    <div className="mt-6 space-y-3">
      <button type="button" onClick={buyNow} disabled={disabled || busy !== null}
        className="w-full rounded-full bg-accent py-3.5 font-medium text-surface transition-colors hover:bg-accent-strong disabled:opacity-50">
        {busy === "buy" ? "Preparing checkout…" : "Buy Now"}
      </button>
      <button type="button" onClick={addToCart} disabled={disabled || busy !== null}
        className="w-full rounded-full border border-accent py-3.5 font-medium text-accent transition-colors hover:bg-accent/5 disabled:opacity-50">
        {busy === "add" ? "Adding…" : "Add to Cart"}
      </button>
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
    </div>
  );
}
