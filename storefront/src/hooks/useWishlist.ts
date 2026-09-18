"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useHasSession } from "@/components/session/SessionProvider";

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

/**
 * The membership GET runs only for a visitor who actually has a session.
 *
 * WHY IT IS GATED AT ALL. Signed out, this GET is a guaranteed 401 — the BFF route
 * refuses it before it reaches Django (app/api/wishlist/[[...sku]]/route.ts) — and the
 * empty set the fetcher falls back to on a 401 is the same empty set the gate produces.
 * So nothing on screen changes; one request per page simply stops being made. That
 * matters because THIS HOOK IS EVERYWHERE: the header heart, every product card's heart,
 * and the PDP save button all call it, and they share one `["wishlist","skus"]` key, so
 * a single un-gated consumer is enough to make the request for the whole page.
 *
 * WHERE THE ANSWER COMES FROM. `SessionProvider`, mounted in `(shop)/layout.tsx`, which
 * reads the httpOnly cookies server-side and passes down a bare boolean. Page JavaScript
 * never sees a token — see that file for why the cookies stay unreadable.
 *
 * `enabled` is an explicit override that beats the context, kept so a caller which
 * already holds the answer (the Header, which resolves it for the AccountMenu anyway)
 * can hand it straight over. Omitted, the context decides; with no provider above, the
 * hook behaves exactly as it did before this gate existed and fetches.
 */
export function useWishlist({ enabled }: { enabled?: boolean } = {}) {
  const qc = useQueryClient();
  const hasSession = useHasSession();
  // `??`, never `||`: an explicit `enabled: false` must win, and `false || null` would
  // discard it. Provider absent (null) -> true, the pre-gate behaviour.
  const active = enabled ?? hasSession ?? true;
  const query = useQuery({
    queryKey: KEY, queryFn: fetchSkus, staleTime: 60_000, enabled: active,
  });
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
