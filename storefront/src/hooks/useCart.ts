"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { Cart } from "@/lib/cart-types";
import { EMPTY_CART } from "@/lib/cart-types";

const KEY = ["cart"] as const;

/** Pure optimistic recompute — exported for unit testing. Never rounds; the server
 * re-resolves and returns authoritative strings, this is just instant UI feedback. */
export function applyOptimisticQty(cart: Cart, variantId: number, qty: number): Cart {
  const items = cart.items
    .map((l) => {
      if (l.variant_id !== variantId) return l;
      if (qty <= 0) return null;
      const unit = Number(l.unit_price ?? "0");
      return { ...l, quantity: qty, line_total: (unit * qty).toFixed(2) };
    })
    .filter((l): l is Cart["items"][number] => l !== null);
  const subtotal = items
    .filter((l) => !l.unavailable)
    .reduce((s, l) => s + Number(l.line_total ?? "0"), 0)
    .toFixed(2);
  return { ...cart, items, subtotal };
}

async function fetchCart(): Promise<Cart> {
  const res = await fetch("/api/cart", { method: "GET" });
  return res.ok ? res.json() : EMPTY_CART;
}

export function useCart() {
  const qc = useQueryClient();
  const query = useQuery({ queryKey: KEY, queryFn: fetchCart, staleTime: 30_000 });

  const setQty = useMutation({
    mutationFn: async (v: { variantId: number; quantity: number }) => {
      const res = await fetch(`/api/cart/items/${v.variantId}`, {
        method: "PATCH", headers: { "content-type": "application/json" },
        body: JSON.stringify({ quantity: v.quantity }),
      });
      return res.json() as Promise<Cart>;
    },
    onMutate: async (v) => {
      await qc.cancelQueries({ queryKey: KEY });
      const prev = qc.getQueryData<Cart>(KEY);
      if (prev) qc.setQueryData(KEY, applyOptimisticQty(prev, v.variantId, v.quantity));
      return { prev };
    },
    onError: (_e, _v, ctx) => { if (ctx?.prev) qc.setQueryData(KEY, ctx.prev); },
    onSettled: (data) => { if (data) qc.setQueryData(KEY, data); },
  });

  const addItem = useMutation({
    mutationFn: async (v: { variantId: number; quantity: number }) => {
      const res = await fetch("/api/cart/items", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ variant_id: v.variantId, quantity: v.quantity }),
      });
      return res.json() as Promise<Cart>;
    },
    onSuccess: (data) => qc.setQueryData(KEY, data),
  });

  return { cart: query.data ?? EMPTY_CART, isLoading: query.isLoading, addItem, setQty };
}
