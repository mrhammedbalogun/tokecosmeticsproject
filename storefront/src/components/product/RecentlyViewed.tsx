"use client";
import Image from "next/image";
import Link from "next/link";
import { useEffect, useState } from "react";
import { listRecentlyViewed, type RecentEntry } from "@/lib/recently-viewed";
import { formatMoney, symbolFor } from "@/lib/country";

export function RecentlyViewed({ excludeSlug }: { excludeSlug: string }) {
  const [items, setItems] = useState<RecentEntry[]>([]);
  useEffect(() => {
    // One-shot client-only read: the ring buffer lives in localStorage, so the server and
    // the first (hydration) client render MUST output nothing (items=[] -> null) to stay
    // hydration-safe; only after mount may we read it. Same "subscribe to a browser system"
    // case documented in CountrySuggestionBanner (useSyncExternalStore was unreliable here).
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional post-mount localStorage read; see note above
    setItems(listRecentlyViewed().filter((e) => e.slug !== excludeSlug).slice(0, 6));
  }, [excludeSlug]);
  if (items.length === 0) return null;
  return (
    <section aria-label="Recently viewed" className="mt-16">
      <h2 className="font-display text-2xl">Recently viewed</h2>
      <div className="mt-6 flex gap-4 overflow-x-auto pb-2">
        {items.map((e) => (
          <Link key={e.slug} href={`/product/${e.slug}`} className="w-36 shrink-0">
            <div className="relative aspect-[3/4] overflow-hidden rounded-[var(--radius-card)] bg-beige">
              {e.image && <Image src={e.image} alt={e.name} fill sizes="144px" className="object-cover" />}
            </div>
            <p className="mt-2 line-clamp-2 text-xs">{e.name}</p>
            {e.from_price && (
              <p className="text-xs font-medium">
                {formatMoney(e.from_price, e.currency, symbolFor(e.currency))}
              </p>
            )}
          </Link>
        ))}
      </div>
    </section>
  );
}
