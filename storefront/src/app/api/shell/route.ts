import { cookies } from "next/headers";
import { ACCESS_COOKIE, CART_COOKIE, REFRESH_COOKIE } from "@/lib/auth";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";
import { announcementsFrom, getHomepage } from "@/lib/cms";
import { ANNOUNCEMENTS } from "@/lib/home-content";

/**
 * Everything the STATIC shell cannot know at build time, in one request.
 *
 * ── WHY THIS EXISTS ─────────────────────────────────────────────────────────────────
 *
 * The routes under `(static-shop)` are prerendered to URL-keyed HTML, so nothing in
 * them may depend on who is asking or which market they are in. Three values do:
 *
 *   signedIn / hasGuestCart  — read from httpOnly cookies, which page JS cannot see and
 *                              MUST NOT be able to see (`lib/auth.ts`: a JWT is never
 *                              reachable from browser JavaScript). So the server has to
 *                              answer, and it answers with bare booleans — no token, no
 *                              cookie name, nothing that could impersonate anyone. Same
 *                              contract `SessionProvider` has had since Plan-5.
 *   announcements            — CMS strip banners are country-targeted
 *                              (`Banner.countries`, apps/cms/models.py). Baking one
 *                              market's strips into shared HTML is exactly the
 *                              wrong-market bug Task 12B guards against.
 *
 * ── WHY ONE ROUTE AND NOT THREE ─────────────────────────────────────────────────────
 *
 * Because a static page trades a server RENDER for a server CALL, and the trade is only
 * worth making once. Three endpoints would mean three invocations per view and the
 * arithmetic stops favouring static rendering at all. The shell asks one question.
 *
 * Deliberately NOT cached (`no-store`): the whole payload is per-visitor. The expensive
 * half is not — `getHomepage` is a 60s tagged fetch that Django flushes on any CMS write
 * (`apps/cms/revalidate.py`), so the data cache absorbs the CMS read and only the cookie
 * reads are genuinely per-request.
 */
export async function GET() {
  const jar = await cookies();

  // ACCESS **OR** REFRESH, mirroring `hasSession()` in every other BFF route. Access
  // alone would be wrong: it lives 14 minutes, so a shopper twenty minutes into a
  // perfectly good 14-day session would read as anonymous and lose their saved hearts.
  const signedIn = Boolean(
    jar.get(ACCESS_COOKIE)?.value || jar.get(REFRESH_COOKIE)?.value,
  );
  // `cart_id` is httpOnly too, so the browser cannot check this for itself — and asking
  // the API whether a cart exists IS the request the gate is trying to avoid.
  const hasGuestCart = Boolean(jar.get(CART_COOKIE)?.value);

  const country = jar.get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  // A null payload — empty CMS, or the API down — falls back to the Plan-13 fixtures
  // rather than emptying a bar that renders on every page. Identical to what
  // `(shop)/layout.tsx` does server-side for the dynamic half of the site.
  const announcements = announcementsFrom(await getHomepage(country), ANNOUNCEMENTS);

  return Response.json(
    { signedIn, hasGuestCart, announcements },
    // Per-visitor, and it names whether somebody is signed in: it must never be held by
    // a shared cache. `private` is not enough on its own — a CDN that ignores it would
    // hand one shopper's answer to the next.
    { headers: { "cache-control": "private, no-store" } },
  );
}
