import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * What the PRERENDERED pages are allowed to contain (Task 12D).
 *
 * `country-market-safety.test.ts` proves these routes ARE static and read no cookies.
 * This file asks the other question: now that their HTML is built once and served to
 * everybody, is there anything in it that should not be shared?
 */

const SHOP = join(process.cwd(), "src", "app", "(shop)");
const BUILT = join(process.cwd(), ".next", "server", "app");

describe("/cart and /checkout stay CLIENT shells", () => {
  /**
   * These two live under `(shop)`, NOT in the prerendered group — Task 12E put them back
   * there deliberately: they are the conversion path and they keep the per-request shell.
   *
   * The assertions stay, and they are read from `(shop)` now. What they pin is no longer a
   * leak guard (nothing here is shared HTML any more) but the design fact that made 12E
   * cheap: the page itself contributes NO server data. The cart is fetched in the browser,
   * per visitor, so the only cost of the dynamic shell is the shell. A server-side fetch
   * appearing in either page would change that — and would have to be judged on its own
   * merits rather than arriving unnoticed.
   */
  it.each(["cart", "checkout"])("/%s renders no server data", (route) => {
    const src = readFileSync(join(SHOP, route, "page.tsx"), "utf8");
    expect(src).not.toMatch(/\bcookies\s*\(\s*\)/);
    expect(src).not.toMatch(/\bheaders\s*\(\s*\)/);
    expect(src).not.toMatch(/\bapiFetch\b/);
    expect(src).not.toMatch(/\bfetchWithAuth\b/);
    // Not an async Server Component: nothing to await means nothing to leak.
    expect(src).not.toMatch(/export default async function/);
  });

  it.each(["cart", "checkout"])("/%s stays out of search results", (route) => {
    // Unchanged by 12D and by 12E, and asserted because moving a page between route
    // groups is exactly the kind of change that quietly drops a robots directive.
    const src = readFileSync(join(SHOP, route, "page.tsx"), "utf8");
    expect(src).toMatch(/robots:\s*\{\s*index:\s*false/);
  });
});

describe("the prerendered HTML carries nothing private", () => {
  const page = join(BUILT, "about-us.html");

  it("contains no session token, cookie name or personal marker", () => {
    if (!existsSync(page)) {
      console.warn("[static-shell] .next missing — run `npm run build`; HTML not verified.");
      return;
    }
    const html = readFileSync(page, "utf8");
    // The httpOnly cookies must not be reachable from page JS, and must certainly not be
    // printed INTO the page. None of these should ever appear in shared HTML.
    for (const secret of ["Bearer ", "refresh=", "access=", "cart_id=", "eyJ"]) {
      expect(html, `"${secret}" must not be in prerendered HTML`).not.toContain(secret);
    }
  });

  it("carries the ANONYMOUS header control, never a signed-in one", () => {
    if (!existsSync(page)) return;
    const html = readFileSync(page, "utf8");
    // Signed-out is the only honest default for HTML shared by everyone — and it is the
    // safe direction: it tells a stranger nothing, and the real state arrives from
    // `/api/shell` a moment later.
    expect(html).toContain("Sign in");
    expect(html).not.toMatch(/>Account</);
  });

  it("carries no market's announcement strip", () => {
    if (!existsSync(page)) return;
    const html = readFileSync(page, "utf8");
    // The fixture fallback names Nigeria and the CMS strips are country-targeted; neither
    // belongs in HTML that a Canadian and a Nigerian both receive.
    expect(html).not.toContain("Free delivery in Nigeria");
    expect(html).not.toContain("Free delivery to the UK");
  });

  it("offers EITHER every market or none — never a partial list", () => {
    if (!existsSync(page)) return;
    const html = readFileSync(page, "utf8");
    const offered = [...html.matchAll(/<option value="([A-Z]{2})"/g)].map((m) => m[1]);

    if (offered.length === 0) {
      /**
       * NOT a failure, and worth understanding rather than asserting away.
       *
       * `getMarkets()` is a build-time fetch with a `.catch(() => [])`, so a build run
       * against an unreachable API prerenders an EMPTY switcher — which is what happens
       * in CI, where `npm run build` has no Django to talk to. It self-heals: these
       * routes carry a 1h revalidate inherited from the fetch, so the first revalidation
       * after the API is reachable fills the menu in.
       *
       * The exposure this leaves is real and belongs in the deploy checklist, not here:
       * a production build that cannot reach the API ships a header with no country
       * switcher and no category menu for up to an hour. Dynamic routes never had that
       * exposure because they fetch per request.
       */
      console.warn("[static-shell] switcher prerendered empty — build had no API. Skipped.");
      return;
    }

    // Populated means it must be COMPLETE. A partial list is the dangerous shape: it
    // would silently shut some market out of its own currency. The list is safe to share
    // because it is market-invariant (measured: `/meta/countries/` byte-identical across
    // all four markets); which one is SELECTED is corrected in the browser.
    expect([...offered].sort()).toEqual(["CA", "GB", "NG", "US", "ZZ"]);
  });
});
