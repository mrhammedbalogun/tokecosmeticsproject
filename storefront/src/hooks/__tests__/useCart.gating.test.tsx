import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SessionProvider } from "@/components/session/SessionProvider";
import { CartButton } from "@/components/layout/CartButton";

/**
 * The cart gate, by lifecycle flow.
 *
 * `GET /api/cart` MINTS a cart server-side when the browser has no `cart_id`, so the
 * header asking on behalf of a visitor who never added anything wrote a database row for
 * a badge that could only read zero. These tests pin each flow named in the Task 6
 * analysis, in both directions.
 */

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }) }));

const fetchMock = vi.fn();
const CART = {
  id: "cart-1",
  items: [{ variant_id: 7, quantity: 2, unit_price: "10.00", line_total: "20.00" }],
  combos: [],
  subtotal: "20.00",
};

beforeEach(() => {
  fetchMock.mockReset();
  fetchMock.mockResolvedValue({ ok: true, json: async () => CART });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

function mount(
  session: { signedIn: boolean; hasGuestCart: boolean } | null,
  seed?: { data: unknown; staleMs?: number },
) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  // `updatedAt` in the past makes the seeded entry STALE, which is what lets a mount
  // refetch — seeding it fresh would prove nothing, since a fresh entry is not refetched
  // either before or after this change.
  if (seed) {
    qc.setQueryData(["cart"], seed.data, { updatedAt: Date.now() - (seed.staleMs ?? 60_000) });
  }
  const tree = <CartButton />;
  return {
    qc,
    ...render(
      <QueryClientProvider client={qc}>
        {session ? (
          <SessionProvider signedIn={session.signedIn} hasGuestCart={session.hasGuestCart}>
            {tree}
          </SessionProvider>
        ) : (
          tree
        )}
      </QueryClientProvider>,
    ),
  };
}

function cartCalls() {
  return fetchMock.mock.calls.filter((c) => String(c[0]) === "/api/cart");
}

async function settle() {
  await new Promise((r) => setTimeout(r, 25));
}

describe("A. anonymous with NO cart_id", () => {
  it("makes no GET /api/cart, so no guest cart is minted", async () => {
    mount({ signedIn: false, hasGuestCart: false });
    await settle();
    expect(cartCalls()).toHaveLength(0);
  });

  it("still renders the bag, showing an empty count", async () => {
    mount({ signedIn: false, hasGuestCart: false });
    expect(screen.getByRole("button", { name: "Cart, 0 items" })).toBeInTheDocument();
  });
});

describe("B. anonymous WITH an existing cart_id", () => {
  it("still queries and shows the real count", async () => {
    mount({ signedIn: false, hasGuestCart: true });
    await waitFor(() => expect(cartCalls()).toHaveLength(1));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Cart, 2 items" })).toBeInTheDocument(),
    );
  });
});

describe("C. authenticated visitor", () => {
  it("queries even with no cart_id in this browser (the account may hold one)", async () => {
    mount({ signedIn: true, hasGuestCart: false });
    await waitFor(() => expect(cartCalls()).toHaveLength(1));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Cart, 2 items" })).toBeInTheDocument(),
    );
  });
});

describe("D. anonymous adds their first product", () => {
  it("a cart written to the cache by the add turns the query back on and updates the badge", async () => {
    // The add mutation is never gated; it writes the server's cart into the cache. That
    // write is what this asserts against — the badge must follow, and the query resume.
    const { qc } = mount({ signedIn: false, hasGuestCart: false });
    await settle();
    expect(cartCalls()).toHaveLength(0);

    qc.setQueryData(["cart"], CART); // stands in for addItem's onSuccess

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Cart, 2 items" })).toBeInTheDocument(),
    );
    // And the query is live again: an invalidation now refetches, where before the add
    // it would have been ignored.
    qc.invalidateQueries({ queryKey: ["cart"] });
    await waitFor(() => expect(cartCalls().length).toBeGreaterThan(0));
  });
});

describe("G. logout leaves no frozen badge", () => {
  it("a STALE cart left in cache still refetches — the query is not switched off", async () => {
    // SignOutButton calls router.refresh() but does NOT clear the query cache, so the
    // server flags come back false while the old cart is still cached. Without the cache
    // clause the query would be disabled and that count frozen on screen for good. With
    // it, staleness is resolved exactly as it is today.
    fetchMock.mockResolvedValue({ ok: true, json: async () => ({ id: "c", items: [], combos: [], subtotal: "0.00" }) });
    mount({ signedIn: false, hasGuestCart: false }, { data: CART });
    await waitFor(() => expect(cartCalls().length).toBeGreaterThan(0));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Cart, 0 items" })).toBeInTheDocument(),
    );
  });
});

describe("backward compatibility", () => {
  it("with NO SessionProvider above it, the cart query runs exactly as before", async () => {
    mount(null);
    await waitFor(() => expect(cartCalls()).toHaveLength(1));
  });
});
