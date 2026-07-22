"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";

/** Heart toggle. Optimistic; a 401 from the BFF sends the visitor to /login.
 * sku is the default-variant sku (backend wishlist is sku-keyed). The heart sits
 * inside the card <Link>, so clicks are prevented from navigating. */
export function WishlistHeart({ sku, name }: { sku: string | null; name: string }) {
  const [saved, setSaved] = useState(false);
  const router = useRouter();
  if (!sku) return null;

  async function toggle(e: React.MouseEvent) {
    e.preventDefault(); // the heart sits inside the card <Link>
    if (!sku) return; // re-narrow for the async closure (button only renders with sku)
    const next = !saved;
    setSaved(next);
    const res = next
      ? await fetch("/api/wishlist", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ sku }),
        })
      : await fetch(`/api/wishlist/${encodeURIComponent(sku)}`, { method: "DELETE" });
    if (res.status === 401) {
      setSaved(false);
      router.push("/login");
    } else if (!res.ok) {
      setSaved(!next);
    }
  }

  return (
    <button
      onClick={toggle}
      aria-pressed={saved}
      aria-label={saved ? `Remove ${name} from wishlist` : `Save ${name} to wishlist`}
      className="absolute right-3 top-3 z-10 rounded-full bg-surface/90 p-2 text-lg leading-none shadow-sm backdrop-blur-sm transition-transform hover:scale-110 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
    >
      <span aria-hidden className={saved ? "text-accent" : "text-muted"}>
        {saved ? "♥" : "♡"}
      </span>
    </button>
  );
}
