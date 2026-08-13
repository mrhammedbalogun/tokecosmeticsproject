"use client";
import Link from "next/link";
import { useWishlist } from "@/hooks/useWishlist";

/** Header heart → the account wishlist. Same 1.5-stroke pen as the bag icon.
 * The dot (not a count — a wishlist is a mood board, not a ledger) simply says
 * "there's something saved here". Signed-out visitors land on login via the
 * account guard, which is exactly the nudge we want. */
function HeartIcon({ filled }: { filled: boolean }) {
  return (
    <svg
      aria-hidden
      viewBox="0 0 24 24"
      className="h-[22px] w-[22px]"
      fill={filled ? "currentColor" : "none"}
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M12 20.3S4 15.4 4 9.9C4 7.2 6.1 5 8.7 5c1.4 0 2.6.7 3.3 1.7C12.7 5.7 14 5 15.3 5 18 5 20 7.2 20 9.9c0 5.5-8 10.4-8 10.4Z" />
    </svg>
  );
}

export function WishlistLink() {
  const { skus } = useWishlist();
  const hasSaves = skus.size > 0;
  return (
    <Link
      href="/account/wishlist"
      aria-label={hasSaves ? "Wishlist (has saved items)" : "Wishlist"}
      className="relative inline-flex items-center justify-center p-1 transition-colors hover:text-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
    >
      <HeartIcon filled={false} />
      {hasSaves && (
        <span
          aria-hidden
          className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full bg-accent"
        />
      )}
    </Link>
  );
}
