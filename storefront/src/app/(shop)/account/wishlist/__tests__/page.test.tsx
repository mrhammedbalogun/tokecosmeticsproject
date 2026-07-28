import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { WishlistItem } from "@/components/account/WishlistGrid";

const store = new Map<string, string>();
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (n: string) => (store.has(n) ? { name: n, value: store.get(n) } : undefined),
    set: (n: string, v: string) => store.set(n, v),
    delete: (n: string) => store.delete(n),
  }),
}));

class Redirected extends Error {
  constructor(public to: string) { super(`NEXT_REDIRECT ${to}`); }
}
vi.mock("next/navigation", () => ({
  redirect: (to: string) => { throw new Redirected(to); },
  // ProductCard embeds the WishlistHeart client island, which calls useRouter().
  useRouter: () => ({ push: vi.fn() }),
}));

import WishlistPage from "../page";

const WISHLIST: WishlistItem[] = [
  {
    sku: "TOKE-SHEA",
    product: {
      name: "Shea Butter Cream", slug: "shea-butter-cream", brand: "toke",
      is_featured: false, from_price: "4900.00", currency: "NGN",
      image: null, hover_image: null,
      default_variant_id: 7, default_sku: "TOKE-SHEA",
      rating_avg: "4.50", rating_count: 12,
    },
    created_at: "2026-07-01T00:00:00Z",
  },
];

function renderPage(page: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{page}</QueryClientProvider>);
}

const originalFetch = global.fetch;
beforeEach(() => {
  process.env.API_URL = "http://backend:8000";
  store.clear();
  store.set("access", "AAA");
  store.set("refresh", "RRR");
  global.fetch = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(WISHLIST), {
      status: 200, headers: { "content-type": "application/json" },
    }),
  ) as unknown as typeof fetch;
});
afterEach(() => { global.fetch = originalFetch; vi.restoreAllMocks(); });

describe("wishlist page", () => {
  it("fetches /me/wishlist/ and hands the list to WishlistGrid", async () => {
    renderPage(await WishlistPage());

    expect(screen.getByRole("heading", { name: /wishlist/i })).toBeInTheDocument();
    expect(screen.getByText("Shea Butter Cream")).toBeInTheDocument();
  });

  it("forwards the country cookie to /me/wishlist/ (non-NG shoppers must not get NG-resolved cards)", async () => {
    store.set("country", "GB");
    renderPage(await WishlistPage());

    const f = global.fetch as unknown as ReturnType<typeof vi.fn>;
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("http://backend:8000/api/v1/me/wishlist/");
    expect(new Headers((init as RequestInit).headers).get("X-Country")).toBe("GB");
  });

  it("bounces to /account/wishlist (not /account) on a stale session with no refresh cookie", async () => {
    store.delete("access");
    store.delete("refresh");
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "Not authenticated." }), {
        status: 401, headers: { "content-type": "application/json" },
      }),
    ) as unknown as typeof fetch;

    await expect(WishlistPage()).rejects.toThrow(
      "NEXT_REDIRECT /login?next=%2Faccount%2Fwishlist",
    );
  });
});
