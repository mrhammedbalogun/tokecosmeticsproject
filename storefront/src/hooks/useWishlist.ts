"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

/** One shared ["wishlist"] cache (a Set of saved skus) so every heart — product
 * cards, the PDP, the header — shows the shopper's REAL saved state and they all
 * move together. Before this hook each heart held its own useState(false), so a
 * saved product rendered an empty heart until you clicked it (and clicking it
 * then REMOVED it server-side while the UI showed "saved").
 *
 * Signed-out shoppers: the GET answers 401 → empty set, hearts render unsaved,
 * and the first toggle bounces to /login (handled by the caller via the thrown
 * WishlistAuthError). */

const KEY = ["wishlist", "skus"] as const;

export class WishlistAuthError extends Error {
  name = "WishlistAuthError";
}

async function fetchSkus(): Promise<Set<string>> {
  const res = await fetch("/api/wishlist");
  if (!res.ok) return new Set(); // 401 signed-out (or transient) → no saved marks
  const data: { sku: string }[] = await res.json().catch(() => []);
  return new Set(data.map((i) => i.sku));
}

export function useWishlist() {
  const qc = useQueryClient();
  const query = useQuery({ queryKey: KEY, queryFn: fetchSkus, staleTime: 60_000 });
  const skus = query.data ?? new Set<string>();

  const toggle = useMutation({
    mutationFn: async (v: { sku: string; save: boolean }) => {
      const res = v.save
        ? await fetch("/api/wishlist", {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify({ sku: v.sku }),
          })
        : await fetch(`/api/wishlist/${encodeURIComponent(v.sku)}`, { method: "DELETE" });
      if (res.status === 401) throw new WishlistAuthError();
      if (!res.ok) throw new Error(`Wishlist request failed: ${res.status}`);
    },
    onMutate: async (v) => {
      await qc.cancelQueries({ queryKey: KEY });
      const prev = qc.getQueryData<Set<string>>(KEY);
      const next = new Set(prev ?? []);
      if (v.save) next.add(v.sku);
      else next.delete(v.sku);
      qc.setQueryData(KEY, next);
      return { prev };
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(KEY, ctx.prev);
      else qc.removeQueries({ queryKey: KEY });
    },
  });

  return {
    skus,
    isSaved: (sku: string) => skus.has(sku),
    toggle,
    /** For code outside react-query (the account grid) after it mutates the
     * server list itself — pulls the sku set back in line. */
    invalidate: () => qc.invalidateQueries({ queryKey: KEY }),
  };
}
