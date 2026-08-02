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
    for (const route of ["(shop)/products", "(shop)/product/[slug]", "(shop)/category/[slug]"]) {
      expect(existsSync(join(APP, route, "loading.tsx"))).toBe(true);
    }
  });
});
