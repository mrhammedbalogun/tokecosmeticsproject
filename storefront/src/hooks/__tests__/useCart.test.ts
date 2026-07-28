import { describe, it, expect, vi, afterEach } from "vitest";
import * as React from "react";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { applyOptimisticQty, useCart } from "@/hooks/useCart";
import type { Cart } from "@/lib/cart-types";

const cart: Cart = {
  id: "c1", kind: "standard", status: "active", country: "NG", currency: "NGN",
  items: [
    { id: 1, variant_id: 10, sku: "A", name: "A", variant_name: {}, quantity: 2, unit_price: "100.00", line_total: "200.00", unavailable: false },
  ],
  subtotal: "200.00", has_unavailable: false,
};

describe("applyOptimisticQty", () => {
  it("updates a line quantity and recomputes its line total + subtotal", () => {
    const next = applyOptimisticQty(cart, 10, 3);
    expect(next.items[0].quantity).toBe(3);
    expect(next.items[0].line_total).toBe("300.00");
    expect(next.subtotal).toBe("300.00");
  });

  it("removes the line when quantity hits 0", () => {
    const next = applyOptimisticQty(cart, 10, 0);
    expect(next.items).toHaveLength(0);
    expect(next.subtotal).toBe("0.00");
  });

  it("is a no-op for an unknown variant", () => {
    const next = applyOptimisticQty(cart, 999, 5);
    expect(next.items[0].quantity).toBe(2);
  });
});

// Fix 4 (15d final review): both mutationFns called res.json() without checking res.ok,
// so an HTTP error resolved as "success" — addItem's onSuccess (and setQty's onSettled)
// then wrote the ERROR BODY into the ["cart"] cache, poisoning it, and the catch-based
// error UI in WishlistGrid/BuyButtons never fired because nothing ever rejected.
const KEY = ["cart"] as const;

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}

function wrapper(qc: QueryClient) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(QueryClientProvider, { client: qc }, children);
  };
}

describe("useCart — HTTP error handling", () => {
  const originalFetch = global.fetch;
  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("addItem rejects on a non-ok response and leaves the cart cache untouched", async () => {
    const qc = makeClient();
    qc.setQueryData(KEY, cart); // fresh (staleTime 30s) -> the mounted useQuery won't GET it

    global.fetch = vi.fn(async () =>
      new Response(JSON.stringify({ detail: "Something went wrong." }), { status: 400 }),
    ) as unknown as typeof fetch;

    const { result } = renderHook(() => useCart(), { wrapper: wrapper(qc) });

    await expect(
      result.current.addItem.mutateAsync({ variantId: 10, quantity: 1 }),
    ).rejects.toBeTruthy();

    // The error body must never have landed in the cache — it stays exactly what it was.
    expect(qc.getQueryData(KEY)).toEqual(cart);
  });

  it("setQty rolls back the optimistic update on a non-ok response", async () => {
    const qc = makeClient();
    qc.setQueryData(KEY, cart);

    global.fetch = vi.fn(async () =>
      new Response(JSON.stringify({ detail: "Out of stock." }), { status: 409 }),
    ) as unknown as typeof fetch;

    const { result } = renderHook(() => useCart(), { wrapper: wrapper(qc) });

    result.current.setQty.mutate({ variantId: 10, quantity: 5 });

    // Once the rejected mutation settles, onError must have restored the prior cart —
    // never the optimistic (now-wrong) quantity, and never the error response body
    // (the pre-fix bug: onSettled fed the error body straight into the cache).
    await waitFor(() => expect(result.current.setQty.isError).toBe(true));
    expect(qc.getQueryData(KEY)).toEqual(cart);
  });
});
