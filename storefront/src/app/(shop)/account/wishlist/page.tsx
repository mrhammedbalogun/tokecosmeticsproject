import type { Metadata } from "next";
import { fetchWithAuthOrBounce } from "@/lib/session";
import { WishlistGrid, type WishlistItem } from "@/components/account/WishlistGrid";

export const metadata: Metadata = { title: "Wishlist" };

export default async function WishlistPage() {
  // This fetch is the page's gate; `/account/wishlist` is the literal current path so
  // an expired session bounces back HERE after renewal — same pattern as the profile,
  // addresses, and orders pages.
  const items = await fetchWithAuthOrBounce<WishlistItem[]>(
    "/me/wishlist/", "/account/wishlist",
  );

  return (
    <div>
      <h2 className="font-display text-2xl">Wishlist</h2>
      <div className="mt-6">
        <WishlistGrid initial={items} />
      </div>
    </div>
  );
}
