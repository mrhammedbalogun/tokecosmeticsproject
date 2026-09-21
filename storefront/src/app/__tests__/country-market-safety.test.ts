import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * THE SHOP'S HTML VARIES BY MARKET, SO IT MUST NEVER BE CACHED BY URL ALONE.
 *
 * ── THE BUG THIS EXISTS TO CATCH ────────────────────────────────────────────────────
 *
 * Every country-dependent route in this app resolves its market the same way:
 *
 *     const country = (await cookies()).get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
 *
 * That `?? DEFAULT_COUNTRY` is correct for a first-time visitor and catastrophic under
 * `export const dynamic = "force-static"`. Next's own documentation
 * (`node_modules/next/dist/docs/01-app/02-guides/caching-without-cache-components.md`,
 * the `'force-static'` bullet) says it "forces `cookies`, `headers()` and
 * `useSearchParams()` to return EMPTY VALUES". So the cookie read returns `undefined`,
 * the `??` swallows it, and every visitor on earth is served Nigerian prices in naira —
 * silently. It would typecheck, it would build, and every other test in this suite would
 * still pass. There is no runtime error anywhere in that chain.
 *
 * The same wrong-market outcome is reachable WITHOUT `force-static`: anything that makes
 * a country-dependent route prerender to a URL-keyed HTML entry does it. `generateStaticParams`,
 * `cacheComponents`/PPR and a `use cache` around the wrong component all qualify. So the
 * primary assertion below is not about a keyword — it is about the BUILD OUTPUT.
 *
 * ── WHY /product/[slug] IS THE SHARPEST CASE ────────────────────────────────────────
 *
 * Measured against production on 2026-09-16, one URL, four markets:
 *
 *     /product/toke-naturals-scalp-rescue-growth-set   country=NG -> 200
 *                                                      country=GB -> 404
 *                                                      country=US -> 404
 *                                                      country=ZZ -> 404
 *
 * A product's very EXISTENCE is market-scoped (`Product.available_countries`). Caching
 * that page by URL would not merely show the wrong price; it would decide, for every
 * visitor, whether the product exists at all — from whichever market rendered first.
 */

const APP = join(process.cwd(), "src", "app");
const SHOP = join(APP, "(shop)");
const STATIC_SHOP = join(APP, "(static-shop)");

/**
 * The routes that live in the prerendered group — the nine Task 12D moved here, plus
 * `/careers/[slug]` (Plan-45).
 *
 * `/cart` and `/checkout` were in this list until Task 12E and are DELIBERATELY not:
 * they are the conversion path, and the decision was that they keep the per-request
 * `(shop)` shell rather than trade it for a prerendered one. They are therefore covered
 * by the `(shop)` prerender BAN above instead — the same rule, from the other end.
 *
 * `/careers/[slug]` is the first DYNAMIC segment in this group, and it belongs here for
 * the same reason the other nine do: a job advert is the same bytes for every visitor,
 * in every market, signed in or not. It earns its place by `generateStaticParams` (every
 * open role is built at deploy time) plus a revalidating fetch tagged `careers`, which
 * Django flushes on every posting write — so it is prerendered and still never stale.
 * It appears in the manifest's `dynamicRoutes` rather than its `routes`, which the check
 * below already unions.
 */
const STATIC_TARGETS = [
  "/about-us", "/blog", "/careers", "/careers/[slug]", "/contact-us", "/disclaimer",
  "/follow-us", "/skin-quiz", "/entrepreneurial-program", "/become-a-distributor",
];

/** Every URL path served by a page under the `(shop)` segment. Route groups are not
 *  part of the URL, so `(shop)/about-us/page.tsx` is `/about-us`. */
/** Source with comments removed.
 *
 * Every scan below looks for CALLS, and a call in a comment is not a call. This file
 * documents its own reasoning at length and so do the layouts it reads — the first
 * version matched the words "headers()" inside the sentence explaining why
 * `(static-shop)` must never call it, and failed. A guard that a comment can trip is one
 * people learn to edit around.
 *
 * Deliberately simple: it does not parse strings, so a `//` inside a URL literal takes
 * the rest of that line with it. That can only ever HIDE a call from these scans, never
 * invent one, and no call site in this app puts a cookie read after a URL on one line.
 */
function code(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
}

function groupRoutes(dir = SHOP, prefix = ""): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    if (entry === "__tests__") continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      // A parenthesised folder is a route group: it organises files, not URLs.
      const segment = /^\(.*\)$/.test(entry) ? prefix : `${prefix}/${entry}`;
      out.push(...groupRoutes(full, segment));
    } else if (entry === "page.tsx" || entry === "page.ts") {
      out.push(prefix === "" ? "/" : prefix);
    }
  }
  return out;
}

/** Every route segment file in the app (pages, layouts and route handlers). */
function segmentFiles(dir = APP): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    if (entry === "__tests__") continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out.push(...segmentFiles(full));
    else if (/^(page|layout|route|template|default)\.tsx?$/.test(entry)) out.push(full);
  }
  return out;
}

describe("the market must never be cached by URL", () => {
  it("THE PREMISE: the shop layout renders country-targeted content", () => {
    /**
     * Asserted rather than assumed, because the whole ban below rests on it. The layout
     * reads the country cookie and feeds it to `getHomepage`, whose announcement strips
     * are filtered by `Banner.countries` (apps/cms/models.py) — so the layout's own HTML
     * differs between markets, and every route it wraps inherits that.
     *
     * When that stops being true — Task 12's actual goal — this test fails FIRST, and
     * whoever changed it has to come here and relax the ban deliberately rather than
     * discover months later that a prerendered page has been serving NG strips to Canada.
     */
    const layout = readFileSync(join(SHOP, "layout.tsx"), "utf8");
    expect(layout).toMatch(/COUNTRY_COOKIE/);
    expect(layout).toMatch(/getHomepage\(\s*currentCountry\s*\)/);
  });

  it("NO SEGMENT THAT READS A COOKIE MAY FORCE STATIC RENDERING", () => {
    // The fast tripwire. It needs no build, so it fails in the same second the mistake is
    // typed — where the manifest check below would only catch it after `next build`.
    // Scoped to cookie-reading segments rather than banned outright: `force-static` is a
    // legitimate tool on a page that reads no request state, and a blanket ban would be a
    // rule nobody could justify later.
    const offenders: string[] = [];
    for (const file of segmentFiles()) {
      const src = code(readFileSync(file, "utf8"));
      const readsCookies = /\bcookies\s*\(\s*\)/.test(src);
      const forcesStatic = /export\s+const\s+dynamic\s*=\s*["'](force-static|error)["']/.test(src);
      if (readsCookies && forcesStatic) offenders.push(file.slice(APP.length));
    }
    expect(offenders, "force-static empties cookies(); these segments read one").toEqual([]);
  });

  it("NO (shop) ROUTE MAY BE STATICALLY PRERENDERED, by any mechanism", () => {
    /**
     * The real guard, and the reason this file is worth having: it asserts on what Next
     * ACTUALLY DID, not on what the source appears to say. A static import graph cannot
     * answer this question — importing a module that reads a cookie is not the same as
     * reading one during a render, and trying it that way classified `/forgot-password`
     * (genuinely, safely static) as country-dependent. Next decides by execution, and
     * `prerender-manifest.json` is where it writes the answer down.
     *
     * Because this reads the build output, it catches force-static, `generateStaticParams`,
     * `cacheComponents`/PPR and `use cache` alike — anything that turns a market-dependent
     * route into a URL-keyed HTML entry.
     */
    const manifestPath = join(process.cwd(), ".next", "prerender-manifest.json");
    if (!existsSync(manifestPath)) {
      // Deliberately not a silent skip: say out loud that the strongest assertion in this
      // file did not run. CI (`.github/workflows/ci-frontend.yml`) runs only `npm run build`
      // and never vitest, so this check bites locally or not at all until that changes.
      console.warn(
        "[country-market-safety] .next/prerender-manifest.json missing — run `npm run build` " +
        "first; the prerender ban was NOT verified in this run.",
      );
      return;
    }
    const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
    const prerendered = new Set([
      ...Object.keys(manifest.routes ?? {}),
      ...Object.keys(manifest.dynamicRoutes ?? {}),
    ]);

    const leaked = groupRoutes(SHOP).filter((route) => prerendered.has(route));
    expect(
      leaked.sort(),
      "these (shop) routes were prerendered to URL-keyed HTML, which one market would win",
    ).toEqual([]);
  });

  it("the route inventory itself is sane, so the check above cannot pass vacuously", () => {
    // If `shopRoutes()` ever returned [] — a refactor moving the group, a rename — the ban
    // would pass by finding nothing to check. Pin the shape instead of the exact count, so
    // adding a page does not fail the build for no reason.
    const routes = groupRoutes(SHOP);
    expect(routes.length).toBeGreaterThan(20);
    expect(routes).toContain("/product/[slug]");
    expect(routes).toContain("/page/[slug]");
    expect(routes).toContain("/");
  });
});

/**
 * THE OTHER HALF OF THE SAME RULE (Task 12D).
 *
 * `(shop)` may not be prerendered because its layout reads cookies. `(static-shop)` is
 * prerendered ON PURPOSE — and that is only safe for as long as nothing in it reads a
 * cookie or a header. The ban above and the requirement below are one rule stated from
 * both ends: a route is prerendered if and only if its shell asks the server nothing
 * about who is looking.
 */
describe("the prerendered group must stay prerenderable", () => {
  it("its layout reads NO cookies and NO headers", () => {
    // The single property that makes the nine routes static. If it ever stops holding,
    // they silently become dynamic again and the whole task is undone with no test
    // failing anywhere else.
    const layout = code(readFileSync(join(STATIC_SHOP, "layout.tsx"), "utf8"));
    expect(layout).not.toMatch(/\bcookies\s*\(\s*\)/);
    expect(layout).not.toMatch(/\bheaders\s*\(\s*\)/);
    expect(layout).not.toMatch(/COUNTRY_COOKIE/);
  });

  it("no page in it performs a dynamic read of its own", () => {
    const offenders = groupRoutes(STATIC_SHOP).length === 0 ? ["<no routes found>"] : [];
    for (const file of segmentFiles(STATIC_SHOP)) {
      const src = code(readFileSync(file, "utf8"));
      if (/\bcookies\s*\(\s*\)/.test(src) || /\bheaders\s*\(\s*\)/.test(src)) {
        offenders.push(file.slice(APP.length));
      }
    }
    expect(offenders, "a dynamic read here quietly un-statics the route").toEqual([]);
  });

  it("holds exactly the routes listed above, and nothing else", () => {
    // A future page dropped in here would be prerendered by inheritance — which is fine
    // only if somebody decided that deliberately. This makes them decide.
    expect(groupRoutes(STATIC_SHOP).sort()).toEqual([...STATIC_TARGETS].sort());
  });

  it("EVERY ONE of them is actually prerendered in the build output", () => {
    const manifestPath = join(process.cwd(), ".next", "prerender-manifest.json");
    if (!existsSync(manifestPath)) {
      console.warn("[country-market-safety] .next missing — static-group check NOT verified.");
      return;
    }
    const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
    const prerendered = new Set([
      ...Object.keys(manifest.routes ?? {}),
      ...Object.keys(manifest.dynamicRoutes ?? {}),
    ]);
    const missing = STATIC_TARGETS.filter((route) => !prerendered.has(route));
    expect(missing, "these were meant to be static and are being rendered per request")
      .toEqual([]);
  });
});
