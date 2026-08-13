"use client";
import { useRef } from "react";
import { useRouter } from "next/navigation";
import { useWishlist, WishlistAuthError } from "@/hooks/useWishlist";

/** Heart toggle on product cards. Saved state comes from the shared ["wishlist"]
 * cache (useWishlist), so a product the shopper saved last week renders filled on
 * first paint of the list — every heart on the page moves together, including the
 * header's. Optimistic; the hook rolls the cache back on any failure, and a 401
 * sends the visitor to /login. sku is the default-variant sku (backend wishlist is
 * sku-keyed). The heart sits inside the card <Link>, so clicks must not navigate. */
export function WishlistHeart({ sku, name }: { sku: string | null; name: string }) {
  const { isSaved, toggle } = useWishlist();
  const router = useRouter();
  // A ref, not toggle.isPending: mutation state propagates asynchronously, so a
  // rapid double-click could still race a POST against a DELETE without it.
  const inFlight = useRef(false);
  if (!sku) return null;

  const saved = isSaved(sku);
  const pending = toggle.isPending;

  function onClick(e: React.MouseEvent) {
    e.preventDefault(); // the heart sits inside the card <Link>
    if (!sku || inFlight.current) return; // one request at a time — drop double-clicks
    inFlight.current = true;
    toggle.mutate(
      { sku, save: !saved },
      {
        onError: (err) => { if (err instanceof WishlistAuthError) router.push("/login"); },
        onSettled: () => { inFlight.current = false; },
      },
    );
  }

  return (
    <button
      onClick={onClick}
      disabled={pending}
      aria-pressed={saved}
      aria-busy={pending}
      aria-label={saved ? `Remove ${name} from wishlist` : `Save ${name} to wishlist`}
      className="absolute right-3 top-3 z-10 rounded-full bg-surface/90 p-2 text-lg leading-none shadow-sm backdrop-blur-sm transition-transform hover:scale-110 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-70"
    >
      <span aria-hidden className={saved ? "text-accent" : "text-muted"}>
        {saved ? "♥" : "♡"}
      </span>
    </button>
  );
}
