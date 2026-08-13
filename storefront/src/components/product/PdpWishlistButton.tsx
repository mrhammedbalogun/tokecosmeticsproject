"use client";
import { useRef } from "react";
import { useRouter } from "next/navigation";
import { usePdp } from "@/components/product/PdpContext";
import { useWishlist, WishlistAuthError } from "@/hooks/useWishlist";

/** The PDP's save control — a quiet text affordance under the buy buttons, not a
 * second call-to-action (Add to Cart keeps its solo billing). Saves the SELECTED
 * variant's sku, so "Rose 50ml" and "Rose 100ml" are separate saves — matching the
 * sku-keyed backend and the account grid. Shares the ["wishlist"] cache, so the
 * card hearts and the header dot update the moment this is clicked. */
export function PdpWishlistButton({ name }: { name: string }) {
  const { variant } = usePdp();
  const { isSaved, toggle } = useWishlist();
  const router = useRouter();
  // Ref guard, not toggle.isPending — mutation state propagates asynchronously,
  // so a rapid double-click could race a POST against a DELETE without it.
  const inFlight = useRef(false);
  if (!variant) return null;

  const saved = isSaved(variant.sku);
  const pending = toggle.isPending;

  function onClick() {
    if (!variant || inFlight.current) return;
    inFlight.current = true;
    toggle.mutate(
      { sku: variant.sku, save: !saved },
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
