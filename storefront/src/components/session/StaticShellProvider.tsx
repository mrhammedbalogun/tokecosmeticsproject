"use client";
import { useEffect, useState, type ReactNode } from "react";
import { SessionProvider } from "@/components/session/SessionProvider";
import { AnnouncementBar } from "@/components/layout/AnnouncementBar";
import type { AnnouncementItem } from "@/lib/cms";

interface Shell {
  signedIn: boolean;
  hasGuestCart: boolean;
  announcements: AnnouncementItem[];
}

/**
 * The client half of a statically rendered shop page.
 *
 * `(shop)/layout.tsx` resolves session and market on the SERVER and passes them down.
 * A prerendered page cannot: its HTML is shared by every visitor, so the same three
 * values have to arrive after the page does. One `GET /api/shell` fetches all three.
 *
 * ── WHY IT STARTS AT `false` AND NOT `null` ─────────────────────────────────────────
 *
 * `SessionProvider`'s contract is that a MISSING provider means "nobody told me", and
 * consumers then fall back to fetching (`useWishlist`: `enabled ?? hasSession ?? true`).
 * That is the right default for a component mounted outside the tree — but it is the
 * wrong one here, and choosing it would quietly undo Tasks 5 and 6.
 *
 * React Query fires on mount. If this provider published "unknown" for the ~50ms before
 * `/api/shell` answers, `useWishlist` and `useCart` would both be enabled for that tick
 * and both would fire — the wishlist GET that can only ever 401, and the cart GET that
 * MINTS a cart row and a cookie for a visitor who has never added anything. The gates
 * would be intact in the code and useless in practice.
 *
 * Starting at `false` keeps them shut until there is a reason to open them, and nothing
 * is lost by waiting: `enabled` flips the moment the answer lands, React Query runs the
 * query then, and a signed-in shopper's heart fills a beat later than it would on a
 * dynamic page. An anonymous visitor never makes either request at all, which is
 * precisely what those two tasks were for.
 */
export function StaticShellProvider({ children }: { children: ReactNode }) {
  const [shell, setShell] = useState<Shell | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/shell")
      .then((res) => (res.ok ? res.json() : null))
      .then((data: Shell | null) => {
        if (!cancelled && data) setShell(data);
      })
      // A failed shell fetch must not blank the page. The bar falls back to its fixtures
      // and the session gates stay shut, which is the anonymous experience — degraded,
      // never broken.
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  return (
    <SessionProvider
      signedIn={shell?.signedIn ?? false}
      hasGuestCart={shell?.hasGuestCart ?? false}
    >
      {/* Rendered here rather than in the layout so the bar and the session share one
          fetch. `pending` until the answer lands: the bar's fixture fallback names
          Nigeria, and this HTML is served to every market, so the strip shows its own
          height and nothing else until the real, country-resolved strips arrive. */}
      <AnnouncementBar items={shell?.announcements} pending={shell === null} />
      {children}
    </SessionProvider>
  );
}
