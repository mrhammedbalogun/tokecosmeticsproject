import { existsSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const APP = join(process.cwd(), "src", "app");

describe("the app root must not have a loading.tsx", () => {
  it("BECAUSE IT SILENTLY BREAKS EVERY REDIRECT AND EVERY 404", () => {
    /**
     * Measured 2026-08-02 by running the app. A `loading.tsx` at the app ROOT wraps the
     * whole tree in a Suspense boundary, so Next commits the HTTP status before the body
     * streams. With one present:
     *
     *   /legacy-proof-test  ->  200, no Location   (should be 308 -> /products)
     *   /page/unknown-slug  ->  200                (should be 404)
     *
     * Browsers still follow the streamed client-side navigation, so clicking around looks
     * completely normal — which is why this survived Plan-19's 404 investigation, a full
     * unit-test suite that mocks the fetch, and shipping Plan-24's entire redirect layer.
     * Crawlers see 200 and index the old URL forever.
     *
     * Removing it cost nothing: /products, /product/[slug] and /category/[slug] — the
     * only routes heavy enough to want a skeleton — already have their own.
     */
    expect(existsSync(join(APP, "loading.tsx"))).toBe(false);
  });

  it("the routes that genuinely want a skeleton still have one", () => {
    // So that "delete the root one" is not quietly read as "loading states are banned".
    // A LIST page can keep its skeleton: /products exists for every slug-less request,
    // so its Suspense boundary never has a 404 to suppress.
    for (const route of ["(shop)/products"]) {
      expect(existsSync(join(APP, route, "loading.tsx"))).toBe(true);
    }
  });

  it("DETAIL routes must not have one either — a skeleton on a [slug] page is a soft 404", () => {
    /**
     * Same mechanism as the root case, scoped to the two routes that kept their own
     * skeletons: the boundary commits 200 before the page can call notFound(), so a
     * discontinued product answered 200 forever. Hammed ruled 2026-08-03: a truthful
     * 404 on legacy product URLs (the migration's discontinued catalogue must drop out
     * of Google) beats an instant skeleton on the heaviest pages.
     */
    for (const route of ["(shop)/product/[slug]", "(shop)/category/[slug]"]) {
      expect(existsSync(join(APP, route, "loading.tsx"))).toBe(false);
    }
  });
});
