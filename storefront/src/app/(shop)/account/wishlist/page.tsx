import type { Metadata } from "next";
import { cookies } from "next/headers";
import { fetchWithAuthOrBounce } from "@/lib/session";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";
import { WishlistGrid, type WishlistItem } from "@/components/account/WishlistGrid";

export const metadata: Metadata = { title: "Wishlist" };

export default async function WishlistPage() {
  // This fetch is the page's gate; `/account/wishlist` is the literal current path so
  // an expired session bounces back HERE after renewal — same pattern as the profile,
  // addresses, and orders pages.
  //
  // The country cookie MUST be forwarded: /me/wishlist/ returns country-resolved
  // product cards (price, currency, default_variant_id availability), and without it
  // the backend defaults to NG — a non-NG shopper would see NGN prices and NG stock
  // driving their wishlist's "Add to bag" availability.
  const country = (await cookies()).get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  const items = await fetchWithAuthOrBounce<WishlistItem[]>(
    "/me/wishlist/", "/account/wishlist", { country },
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
