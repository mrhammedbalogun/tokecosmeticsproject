import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { WishlistGrid, type WishlistItem } from "@/components/account/WishlistGrid";
import { onCartDrawerOpen } from "@/lib/cart-ui";
import type { ProductCard as ProductCardData } from "@/lib/catalog";

// ProductCard embeds the WishlistHeart client island, which calls useRouter().
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

type Route = { status: number; body: unknown } | { reject: true };

function mockFetch(routes: Record<string, Route>) {
  const f = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const method = (init?.method ?? "GET").toUpperCase();
    const key = `${method} ${url}`;
    const route = routes[key];
    if (!route) return Promise.reject(new Error(`unexpected fetch: ${key}`));
    if ("reject" in route) return Promise.reject(new Error(`simulated network failure: ${key}`));
    // Null-body statuses (204 for DELETE) reject a non-null Response body at construction.
    const body = route.status === 204 ? null : JSON.stringify(route.body);
    return Promise.resolve(
      new Response(body, {
        status: route.status,
        headers: { "content-type": "application/json" },
      })
    );
  });
  global.fetch = f as unknown as typeof fetch;
  return f;
}

function product(overrides: Partial<ProductCardData> = {}): ProductCardData {
  return {
    name: "Shea Butter Cream", slug: "shea-butter-cream", brand: "toke",
    is_featured: false, from_price: "4900.00", currency: "NGN",
    image: null, hover_image: null,
    default_variant_id: 7, default_sku: "TOKE-SHEA",
    rating_avg: "4.50", rating_count: 12,
    ...overrides,
  };
}

function item(overrides: Partial<WishlistItem> = {}): WishlistItem {
  return {
    sku: "TOKE-SHEA", product: product(), created_at: "2026-07-01T00:00:00Z",
    ...overrides,
  };
}

const originalFetch = global.fetch;

function renderGrid(initial: WishlistItem[]) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <WishlistGrid initial={initial} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  global.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("WishlistGrid", () => {
  it("renders a card per non-null product and a muted row for a null one", () => {
    mockFetch({});
    renderGrid([
      item({ sku: "TOKE-SHEA" }),
      item({ sku: "TOKE-GONE", product: null }),
    ]);

    expect(screen.getByText("Shea Butter Cream")).toBeInTheDocument();
    expect(screen.getByText(/no longer available/i)).toBeInTheDocument();
    expect(screen.getByText("TOKE-GONE")).toBeInTheDocument();
  });

  it("Add to Cart POSTs /api/cart/items with {variant_id, quantity: 1} and opens the drawer", async () => {
    const f = mockFetch({
      "POST /api/cart/items": { status: 200, body: { id: "cart-1", items: [], subtotal: "0.00" } },
    });
    const opened = vi.fn();
    const off = onCartDrawerOpen(opened);
    renderGrid([item()]);

    fireEvent.click(screen.getByRole("button", { name: /add to cart/i }));

    await waitFor(() => expect(f).toHaveBeenCalledWith(
      "/api/cart/items",
      expect.objectContaining({ method: "POST" }),
    ));
    const call = f.mock.calls.find(([url]) => url === "/api/cart/items")!;
    expect(JSON.parse((call[1] as RequestInit).body as string)).toEqual({
      variant_id: 7, quantity: 1,
    });
    await waitFor(() => expect(opened).toHaveBeenCalledTimes(1));
    off();
  });

  it("disables Add to Cart with a region hint when default_variant_id is null", () => {
    mockFetch({});
    renderGrid([item({ product: product({ default_variant_id: null }) })]);

    expect(screen.getByRole("button", { name: /add to cart/i })).toBeDisabled();
    expect(screen.getByText(/not available in your region/i)).toBeInTheDocument();
  });

  it("Remove DELETEs /api/wishlist/{sku}, then re-GETs, and the card disappears", async () => {
    const f = mockFetch({
      "DELETE /api/wishlist/TOKE-SHEA": { status: 204, body: null },
      "GET /api/wishlist": { status: 200, body: [] },
    });
    renderGrid([item()]);

    fireEvent.click(screen.getByRole("button", { name: /^remove$/i }));

    await waitFor(() => expect(f).toHaveBeenCalledWith(
      "/api/wishlist/TOKE-SHEA",
      expect.objectContaining({ method: "DELETE" }),
    ));
    await waitFor(() => expect(f).toHaveBeenCalledWith("/api/wishlist"));
    await waitFor(() => expect(screen.queryByText("Shea Butter Cream")).not.toBeInTheDocument());
  });

  it("remove failure shows the inline error and keeps the card", async () => {
    const f = mockFetch({
      "DELETE /api/wishlist/TOKE-SHEA": { status: 500, body: { detail: "boom" } },
    });
    renderGrid([item()]);

    fireEvent.click(screen.getByRole("button", { name: /^remove$/i }));

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByText("Shea Butter Cream")).toBeInTheDocument();
    // Only the failed DELETE happened against the wishlist endpoint — no re-GET.
    expect(f.mock.calls.filter(([url]) => String(url).startsWith("/api/wishlist"))).toHaveLength(1);
  });

  it("add-to-cart failure shows the inline error and leaves the list unchanged", async () => {
    // Exercises the reject path via a network failure. useCart's addItem mutation also
    // rejects on a non-ok HTTP response (throws instead of resolving the error body as
    // if it were a Cart — see useCart.ts / useCart.test.ts), which drives this same
    // catch branch; not re-tested here to avoid duplicating that coverage.
    mockFetch({
      "POST /api/cart/items": { reject: true },
    });
    renderGrid([item()]);

    fireEvent.click(screen.getByRole("button", { name: /add to cart/i }));

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByText("Shea Butter Cream")).toBeInTheDocument();
  });

  it("empty state renders the browse link", () => {
    mockFetch({});
    renderGrid([]);

    expect(screen.getByText(/your wishlist is empty/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /browse products/i })).toHaveAttribute(
      "href", "/products",
    );
  });
});
