"use client";
import { useRef, useState } from "react";
import { useRouter } from "next/navigation";

/** Heart toggle. Optimistic; a 401 from the BFF sends the visitor to /login.
 * sku is the default-variant sku (backend wishlist is sku-keyed). The heart sits
 * inside the card <Link>, so clicks are prevented from navigating.
 *
 * Hardening: a single in-flight request at a time (rapid double-clicks would
 * otherwise race a POST against a DELETE, or land a duplicate-POST 400 that
 * flips the heart to the wrong state), and every failure path — non-ok
 * response, 401, or a rejected fetch (offline/DNS/abort) — restores the exact
 * prior state so the UI never drifts from the server. */
export function WishlistHeart({ sku, name }: { sku: string | null; name: string }) {
  const [saved, setSaved] = useState(false);
  const [pending, setPending] = useState(false);
  const inFlight = useRef(false);
  const router = useRouter();
  if (!sku) return null;

  async function toggle(e: React.MouseEvent) {
    e.preventDefault(); // the heart sits inside the card <Link>
    if (!sku) return; // re-narrow for the async closure (button only renders with sku)
    if (inFlight.current) return; // one request at a time — drop double-clicks
    inFlight.current = true;
    setPending(true);

    const prior = saved;
    const next = !prior;
    setSaved(next);
    try {
      const res = next
        ? await fetch("/api/wishlist", {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify({ sku }),
          })
        : await fetch(`/api/wishlist/${encodeURIComponent(sku)}`, { method: "DELETE" });
      if (res.status === 401) {
        setSaved(prior);
        router.push("/login");
      } else if (!res.ok) {
        setSaved(prior);
      }
    } catch {
      // fetch rejected (offline / DNS / abort) — undo the optimistic update
      setSaved(prior);
    } finally {
      inFlight.current = false;
      setPending(false);
    }
  }

  return (
    <button
      onClick={toggle}
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
