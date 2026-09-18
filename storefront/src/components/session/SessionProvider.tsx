"use client";
import { createContext, useContext, useMemo, type ReactNode } from "react";

/**
 * "Is somebody signed in?", resolved on the SERVER and handed down.
 *
 * ── WHY A CONTEXT AND NOT A COOKIE READ ─────────────────────────────────────────────
 *
 * The obvious shortcut is for the client to look at the auth cookie itself. It cannot,
 * and must not be able to: `lib/auth.ts` keeps `access` and `refresh` httpOnly
 * specifically so a JWT is never reachable from page JavaScript, and that is worth far
 * more than the requests this saves. So the server — which can read them — answers the
 * question once and passes the ANSWER, a bare boolean. No token, no cookie name, and
 * nothing here that could be used to impersonate anyone.
 *
 * ── WHAT THIS IS NOT ────────────────────────────────────────────────────────────────
 *
 * Not an authentication mechanism, and never a gate on anything that matters. Every
 * real check still happens server-side (`lib/session.ts::requireAuth`, and each BFF
 * route's own session check). A visitor who flipped this boolean in their own browser
 * would earn themselves one wishlist request that answers 401. It exists to stop a
 * guaranteed-useless request, nothing more.
 *
 * ── `null` MEANS "NOBODY TOLD ME" ───────────────────────────────────────────────────
 *
 * The default is null, not false, and the difference is load-bearing. A consumer
 * rendered outside this provider — a future route group, a test that mounts a card on
 * its own — falls back to its PREVIOUS behaviour (fetch) rather than silently losing
 * its wishlist. Failing towards "one extra request" beats failing towards "a signed-in
 * shopper's saves quietly stop showing".
 */
export interface SessionState {
  /** access OR refresh cookie present — mirrors each BFF route's own `hasSession()`. */
  signedIn: boolean;
  /** A `cart_id` cookie is present, i.e. this browser has already been given a cart. */
  hasGuestCart: boolean;
}

const SessionContext = createContext<SessionState | null>(null);

export function SessionProvider({
  signedIn,
  // Defaulted rather than required so a caller that only cares about the session half
  // (the wishlist gate, Task 5) stays a one-prop call. The real safety net is the null
  // context above: no provider at all means "unknown", and consumers keep their old
  // behaviour rather than trusting this default.
  hasGuestCart = false,
  children,
}: {
  signedIn: boolean;
  hasGuestCart?: boolean;
  children: ReactNode;
}) {
  const value = useMemo<SessionState>(
    () => ({ signedIn, hasGuestCart }),
    [signedIn, hasGuestCart],
  );
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

/** True / false when a provider is above, null when there is none. */
export function useHasSession(): boolean | null {
  return useContext(SessionContext)?.signedIn ?? null;
}

/**
 * "Is there a cart on the server worth asking about?" — null when no provider is above.
 *
 * Signed in counts on its own: an account can hold a cart built on another device, with
 * no `cart_id` in THIS browser. Anonymous, the cookie is the only evidence there is.
 */
export function useCartMayExist(): boolean | null {
  const s = useContext(SessionContext);
  return s ? s.signedIn || s.hasGuestCart : null;
}
