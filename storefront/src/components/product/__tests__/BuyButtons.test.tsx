import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BuyButtons } from "@/components/product/BuyButtons";
import { BUYNOW_INTENT_KEY } from "@/lib/buynow-intent";
import { EMPTY_CART } from "@/lib/cart-types";

const push = vi.fn();
const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, refresh }) }));

// A priced, in-stock selection; qty 2 proves the quantity travels with the request.
vi.mock("@/components/product/PdpContext", () => ({
  usePdp: () => ({
    variant: { id: 7, in_stock: true, price: "4900.00" },
    qty: 2,
  }),
}));

/** The cart Django hands back after buy-now adds the item to the STANDARD cart. */
const CART_WITH_ITEM = {
  ...EMPTY_CART,
  id: "cart-1",
  items: [{ variant_id: 7, quantity: 2, unit_price: "4900.00", line_total: "9800.00" }],
  subtotal: "9800.00",
};

/** Route-aware fetch: the mounted useCart query GETs /api/cart, the button POSTs
 * buy-now. One undiscriminated mock would let the query's response masquerade as
 * the buy-now response (or vice versa) and the test would assert on an accident. */
function mockFetch(buyNowResponse: () => Response) {
  const f = vi.fn((url: string | URL, init?: RequestInit) => {
    if (String(url) === "/api/checkout/buy-now" && init?.method === "POST") {
      return Promise.resolve(buyNowResponse());
    }
    return Promise.resolve(new Response(JSON.stringify(EMPTY_CART), { status: 200 }));
  });
  global.fetch = f as unknown as typeof fetch;
  return f;
}

const originalFetch = global.fetch;
let qc: QueryClient;

function renderButtons() {
  qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  // The stale-cache trap this file exists for: the shopper browsed with an empty
  // cart, so ["cart"] holds a FRESH (staleTime 30s) empty cart when they hit Buy Now.
  qc.setQueryData(["cart"], EMPTY_CART);
  render(
    <QueryClientProvider client={qc}>
      <BuyButtons />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  push.mockClear();
  refresh.mockClear();
  sessionStorage.clear();
});
afterEach(() => {
  global.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("BuyButtons — Buy Now", () => {
  it("posts variant+qty, seeds the cart cache with the response, then navigates", async () => {
    const f = mockFetch(() => new Response(JSON.stringify(CART_WITH_ITEM), { status: 200 }));
    renderButtons();

    fireEvent.click(screen.getByRole("button", { name: "Buy Now" }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/checkout"));
    expect(f).toHaveBeenCalledWith(
      "/api/checkout/buy-now",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ variant_id: 7, quantity: 2 }),
      }),
    );
    // Without this, checkout trusts the fresh-for-30s empty cart and renders
    // "Your cart is empty" — the exact live bug this change fixes.
    expect(qc.getQueryData(["cart"])).toEqual(CART_WITH_ITEM);
  });

  it("stashes the intent and routes a signed-out shopper to login, leaving the cache alone", async () => {
    mockFetch(() => new Response(JSON.stringify({ detail: "Not authenticated." }), { status: 401 }));
    renderButtons();

    fireEvent.click(screen.getByRole("button", { name: "Buy Now" }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/login?next=/checkout"));
    expect(JSON.parse(sessionStorage.getItem(BUYNOW_INTENT_KEY)!)).toEqual({
      variant_id: 7,
      quantity: 2,
    });
    expect(qc.getQueryData(["cart"])).toEqual(EMPTY_CART);
  });

  it("shows the fallback error and stays put when the request fails", async () => {
    mockFetch(() => new Response(JSON.stringify({ detail: "boom" }), { status: 500 }));
    renderButtons();

    fireEvent.click(screen.getByRole("button", { name: "Buy Now" }));

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(push).not.toHaveBeenCalled();
    expect(qc.getQueryData(["cart"])).toEqual(EMPTY_CART);
  });

  it("409 out_of_stock shows the just-sold-out message and refreshes, no navigation", async () => {
    mockFetch(() =>
      new Response(JSON.stringify({ detail: "This item just sold out.", code: "out_of_stock" }), {
        status: 409,
      }),
    );
    renderButtons();

    fireEvent.click(screen.getByRole("button", { name: "Buy Now" }));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/just sold out/i),
    );
    expect(push).not.toHaveBeenCalled();
    expect(refresh).toHaveBeenCalled();
  });
});

describe("BuyButtons — Add to Cart", () => {
  it("409 out_of_stock shows the just-sold-out message and refreshes", async () => {
    const f = vi.fn((url: string | URL, init?: RequestInit) => {
      if (String(url) === "/api/cart/items" && init?.method === "POST") {
        return Promise.resolve(
          new Response(
            JSON.stringify({ detail: "This item just sold out.", code: "out_of_stock" }),
            { status: 409 },
          ),
        );
      }
      return Promise.resolve(new Response(JSON.stringify(EMPTY_CART), { status: 200 }));
    });
    global.fetch = f as unknown as typeof fetch;
    renderButtons();

    fireEvent.click(screen.getByRole("button", { name: "Add to Cart" }));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/just sold out/i),
    );
    expect(refresh).toHaveBeenCalled();
  });
});
