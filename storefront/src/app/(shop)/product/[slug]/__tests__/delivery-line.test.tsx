import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import type { ReactElement } from "react";

/**
 * The PDP's personalised delivery label.
 *
 * `/me/addresses/` is private, per-user data. These tests pin the two things that keeps
 * honest — it stays `no-store` and authenticated, and it never blocks the product — plus
 * every fallback, because the label degrading quietly is the whole design (a cosmetic
 * line must never cost a shopper the product page).
 */

const cookieStore = new Map<string, string>();
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (n: string) => (cookieStore.has(n) ? { name: n, value: cookieStore.get(n) } : undefined),
  }),
}));

const notFoundError = new Error("NEXT_NOT_FOUND");
vi.mock("next/navigation", () => ({
  notFound: () => { throw notFoundError; },
}));

import ProductPage from "@/app/(shop)/product/[slug]/page";
import { BuyBox } from "@/components/product/BuyBox";
import { deliveryEstimateFor } from "@/lib/delivery-estimates";

/** The real generic line, imported rather than retyped, so a copy edit to the estimates
 *  table cannot leave these tests asserting a string the app no longer produces. */
const GENERIC = deliveryEstimateFor("NG");
/** What the personaliser does to it: swap the leading clause for the saved place. */
const to = (place: string) => GENERIC.replace(/^Delivery[^:]*:/, `Delivery to ${place}:`);

const PRODUCT = {
  name: "Glow Serum", slug: "glow-serum", brand: null,
  description: "", short_description: "", ingredients: "", directions: "", warnings: "",
  specs: [], faqs: [], audience: [], seo_title: "", seo_description: "",
  variants: [], images: [], videos: [], related: [],
  rating_avg: "0.00", rating_count: 0,
};

/** Walks the returned element tree for the BuyBox and hands back its deliveryLine. */
function deliveryLineOf(tree: ReactElement): string | undefined {
  let found: string | undefined;
  const walk = (node: unknown): void => {
    if (found !== undefined || !node) return;
    if (Array.isArray(node)) return node.forEach(walk);
    const el = node as { type?: unknown; props?: Record<string, unknown> };
    if (!el.props) return;
    if (el.type === BuyBox) { found = el.props.deliveryLine as string; return; }
    walk(el.props.children);
  };
  walk(tree);
  return found;
}

const render = () => ProductPage({ params: Promise.resolve({ slug: "glow-serum" }) });

interface Call { url: string; init: RequestInit; startedAt: number }

/** Routes the two upstream calls this page makes, and records their init options. */
function upstream(opts: {
  product?: unknown; productStatus?: number; productDelayMs?: number;
  addresses?: unknown; addressStatus?: number; addressFails?: boolean;
} = {}) {
  const calls: Call[] = [];
  const f = vi.fn(async (url: string, init: RequestInit = {}) => {
    calls.push({ url: String(url), init, startedAt: Date.now() });
    if (String(url).includes("/me/addresses/")) {
      if (opts.addressFails) throw new Error("network down");
      return new Response(JSON.stringify(opts.addresses ?? []), {
        status: opts.addressStatus ?? 200, headers: { "content-type": "application/json" },
      });
    }
    if (opts.productDelayMs) await new Promise((r) => setTimeout(r, opts.productDelayMs));
    return new Response(JSON.stringify(opts.product ?? PRODUCT), {
      status: opts.productStatus ?? 200, headers: { "content-type": "application/json" },
    });
  });
  global.fetch = f as unknown as typeof fetch;
  return calls;
}

const originalFetch = global.fetch;
beforeEach(() => {
  process.env.API_URL = "http://backend:8000";
  cookieStore.clear();
  cookieStore.set("country", "NG");
});
afterEach(() => { global.fetch = originalFetch; vi.restoreAllMocks(); });

const addressCalls = (c: Call[]) => c.filter((x) => x.url.includes("/me/addresses/"));

describe("anonymous visitor", () => {
  it("gets the generic line and makes NO address request", async () => {
    const calls = upstream();
    const tree = await render();

    expect(deliveryLineOf(tree)).toBe(GENERIC);
    expect(addressCalls(calls)).toHaveLength(0);
  });
});

describe("authenticated visitor", () => {
  beforeEach(() => { cookieStore.set("access", "tok"); cookieStore.set("refresh", "r"); });

  it("personalises the line from the default shipping address", async () => {
    upstream({
      addresses: [
        { label: "Home", city_text: "Ikeja", is_default_shipping: true },
        { label: "Work", city_text: "Yaba", is_default_shipping: false },
      ],
    });
    expect(await render().then(deliveryLineOf)).toBe(to("Ikeja"));
  });

  it("sends the token as a Bearer header and NEVER caches the response", async () => {
    const calls = upstream({ addresses: [] });
    await render();

    const [addr] = addressCalls(calls);
    expect(addr).toBeDefined();
    // Private per-user data: no-store at the fetch layer, and no `next.revalidate`
    // that would put it in the shared data cache.
    expect((addr.init as { cache?: string }).cache).toBe("no-store");
    expect((addr.init as { next?: unknown }).next).toBeUndefined();
    expect(new Headers(addr.init.headers).get("Authorization")).toBe("Bearer tok");
  });

  it("falls back to the generic line when the lookup throws", async () => {
    upstream({ addressFails: true });
    expect(await render().then(deliveryLineOf)).toBe(GENERIC);
  });

  it("falls back to the generic line on a 401 (a lapsed access token)", async () => {
    upstream({ addressStatus: 401, addresses: { detail: "no" } });
    expect(await render().then(deliveryLineOf)).toBe(GENERIC);
  });

  it("falls back to the generic line when the account has no addresses", async () => {
    upstream({ addresses: [] });
    expect(await render().then(deliveryLineOf)).toBe(GENERIC);
  });

  it("uses the first address when none is marked default", async () => {
    upstream({ addresses: [{ label: "Work", city_text: "Yaba", is_default_shipping: false }] });
    expect(await render().then(deliveryLineOf)).toBe(to("Yaba"));
  });
});

describe("the product render does not wait for the address lookup", () => {
  beforeEach(() => { cookieStore.set("access", "tok"); cookieStore.set("refresh", "r"); });

  it("starts BOTH upstream calls before the slower one resolves", async () => {
    // The product fetch is held for 80ms. If the two were still sequential the address
    // call could only start after that; concurrent, they start together.
    const calls = upstream({ productDelayMs: 80, addresses: [] });
    const t0 = Date.now();
    await render();

    const [addr] = addressCalls(calls);
    expect(addr).toBeDefined();
    expect(addr.startedAt - t0).toBeLessThan(50);
  });

  it("still renders the product when the address lookup fails", async () => {
    upstream({ addressFails: true });
    const tree = await render();
    expect(deliveryLineOf(tree)).toBe(GENERIC);
    expect(JSON.stringify(tree)).toContain("glow-serum");
  });
});

describe("product failures are unchanged", () => {
  it("a 404 product still calls notFound(), address lookup notwithstanding", async () => {
    cookieStore.set("access", "tok");
    upstream({ productStatus: 404, product: { detail: "gone" }, addresses: [] });
    await expect(render()).rejects.toThrow("NEXT_NOT_FOUND");
  });

  it("a 500 product still bubbles to the error boundary", async () => {
    upstream({ productStatus: 500, product: { detail: "boom" } });
    await expect(render()).rejects.toMatchObject({ status: 500 });
  });
});
