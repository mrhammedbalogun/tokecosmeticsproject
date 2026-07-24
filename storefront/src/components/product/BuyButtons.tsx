"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { useCart } from "@/hooks/useCart";
import { openCartDrawer } from "@/lib/cart-ui";
import { usePdp } from "@/components/product/PdpContext";

export const BUYNOW_INTENT_KEY = "toke-buynow-intent";

/** Amazon-pattern pair (Decision 14): Buy Now = primary (straight to checkout),
 * Add to Cart = secondary (opens the drawer). Guest Buy Now stashes intent and
 * routes to /login — the resume-into-checkout path is Plan-14 (D6). */
export function BuyButtons() {
  const { variant, qty } = usePdp();
  const { addItem } = useCart();
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
    } catch {
      setError("Could not add to bag — please try again.");
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
      if (!res.ok) throw new Error();
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
