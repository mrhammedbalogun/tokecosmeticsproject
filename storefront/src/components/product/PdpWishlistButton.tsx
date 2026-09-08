"use client";
import { useRef } from "react";
import { useRouter } from "next/navigation";
import type { Variant } from "@/lib/catalog";
import { purchasable, usePdp } from "@/components/product/PdpContext";
import { useWishlist, WishlistAuthError } from "@/hooks/useWishlist";

/** The PDP's save control — a quiet text affordance under the buy buttons, not a
 * second call-to-action (Add to Cart keeps its solo billing). Saves the SELECTED
 * variant's sku, so "Rose 50ml" and "Rose 100ml" are separate saves — matching the
 * sku-keyed backend and the account grid. Shares the ["wishlist"] cache, so the
 * card hearts and the header dot update the moment this is clicked.
 *
 * Since the PDP stopped pre-selecting a variant (2026-09-08) there is usually nothing
 * selected on arrival, and hiding the control until then would have taken saving away
 * from every variable product — a real feature and a real remarketing signal, lost to
 * a change about checkout. So with no selection it saves the first variant on offer,
 * exactly like the card heart on the listing page does. Saving is reversible and costs
 * nobody money; buying the wrong size is the thing that had to stop. */
export function PdpWishlistButton({ name, variants }: { name: string; variants: Variant[] }) {
  const { variant } = usePdp();
  const { isSaved, toggle } = useWishlist();
  const router = useRouter();
  // Ref guard, not toggle.isPending — mutation state propagates asynchronously,
  // so a rapid double-click could race a POST against a DELETE without it.
  const inFlight = useRef(false);
  const target = variant ?? purchasable(variants)[0] ?? variants[0] ?? null;
  if (!target) return null;

  const saved = isSaved(target.sku);
  const pending = toggle.isPending;

  function onClick() {
    if (!target || inFlight.current) return;
    inFlight.current = true;
    toggle.mutate(
      { sku: target.sku, save: !saved },
      {
        onError: (err) => { if (err instanceof WishlistAuthError) router.push("/login"); },
        onSettled: () => { inFlight.current = false; },
      },
    );
  }

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={pending}
      aria-pressed={saved}
      aria-busy={pending}
      aria-label={saved ? `Remove ${name} from wishlist` : `Save ${name} to wishlist`}
      className="mt-3 flex w-full items-center justify-center gap-1.5 text-sm text-muted transition-colors hover:text-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-70"
    >
      <span aria-hidden className={saved ? "text-accent" : ""}>{saved ? "♥" : "♡"}</span>
      {saved ? "Saved to wishlist" : "Save to wishlist"}
    </button>
  );
}
