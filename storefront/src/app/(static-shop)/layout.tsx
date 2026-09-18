import { SessionProvider } from "@/components/session/SessionProvider";
import { StaticShellProvider } from "@/components/session/StaticShellProvider";
import { Header } from "@/components/layout/Header";
import { Footer } from "@/components/layout/Footer";
import { ScrollShrink } from "@/components/layout/ScrollShrink";

/**
 * The shop shell for routes that can be PRERENDERED.
 *
 * ── WHY A SECOND LAYOUT AND NOT A FLAG ON THE FIRST ─────────────────────────────────
 *
 * Because a layout is positional in the App Router: every route beneath it gets its
 * rendering mode, and `(shop)/layout.tsx` reads four cookies and a header. Making THAT
 * file static-capable would have stripped the server-resolved market and session out of
 * the header for the whole site — including `/` and `/product/[slug]`, which stay
 * dynamic for their own reasons and would have gained a header flicker they do not have
 * today, for no benefit at all. A sibling route group confines the change to the nine
 * routes that asked for it; `(shop)/layout.tsx` is untouched.
 *
 * Route groups do not appear in URLs, so `/about-us` is still `/about-us`.
 *
 * `/cart` and `/checkout` were here briefly and are NOT any more (Task 12E): they are the
 * conversion path, and the decision was that they keep the per-request `(shop)` shell —
 * the server-resolved market, the announcement strips and the currency greeting — rather
 * than trade it for a prerendered one. Nothing below is a reason to bring them back; that
 * would be a business call, not a rendering one.
 *
 * ── WHAT MAY AND MAY NOT APPEAR IN THIS HTML ────────────────────────────────────────
 *
 * This HTML is built once and served to everyone, so it must contain nothing that
 * varies by visitor or market:
 *
 *   NOT HERE      the country cookie, the geo header, the session cookies, and the
 *                 CMS announcement strips (country-targeted via `Banner.countries`)
 *   HERE, SAFELY  `getMarkets()` and `getCategoryTree()` inside `<Header clientResolved />`
 *                 — revalidating fetches, not dynamic reads, and both measured
 *                 byte-identical across all four markets on 2026-09-16
 *
 * Everything in the first list arrives after the page does, from `/api/shell`.
 *
 * ── THE CURRENCY POPUP IS DELIBERATELY ABSENT ───────────────────────────────────────
 *
 * `CurrencyWelcomeModal` needs the geo hint, which reaches Server Components as a
 * request header (`proxy.ts` sets `x-geo-country`) — and `headers()` is exactly what a
 * prerendered route may not call. It is a FIRST-VISIT greeting, and a first visit lands
 * on the homepage or a product page, not on `/disclaimer`; both of those are dynamic and
 * still show it. Reintroducing it here would cost every one of these routes its static
 * rendering to greet a visitor who has almost certainly already been greeted.
 */
export default function StaticShopLayout({ children }: { children: React.ReactNode }) {
  return (
    // The OUTER provider is the fallback, and it is the reason a failed `/api/shell`
    // cannot turn into a burst of doomed requests: `StaticShellProvider` publishes the
    // real answer when it has one, and this guarantees a defined `false` underneath it
    // either way. Without it a consumer would read `null` — "nobody told me" — and fetch.
    <SessionProvider signedIn={false} hasGuestCart={false}>
      <StaticShellProvider>
        <ScrollShrink />
        <Header clientResolved />
        <main className="flex-1">{children}</main>
        <Footer />
      </StaticShellProvider>
    </SessionProvider>
  );
}
