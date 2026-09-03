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

/** A BFF error body ({ detail, ... }) is not a Cart — surfacing it as one poisons the
 * ["cart"] cache and the render tree that reads it. Thrown so onError/catch paths run
 * instead of onSuccess/onSettled; status and the backend's machine code ride along
 * (code "out_of_stock" = the stock cap ate the whole add — "just sold out"). */
export class CartRequestError extends Error {
  constructor(public status: number, public code?: string) {
    super(`Cart request failed: ${status}`);
  }
}

export function isJustSoldOut(e: unknown): boolean {
  return e instanceof CartRequestError && e.code === "out_of_stock";
}

/** The combo half of the same signal: the scarcest component cannot fill another box.
 *  Distinct from `combo_unavailable`, which means "not sold in this market at all" —
 *  one is "come back later", the other is "never here", and the copy differs. */
export function isComboSoldOut(e: unknown): boolean {
  return e instanceof CartRequestError && e.code === "combo_out_of_stock";
}

export function isComboUnavailable(e: unknown): boolean {
  return e instanceof CartRequestError && e.code === "combo_unavailable";
}

/** Pure optimistic recompute for a bundle's quantity — the combo twin of
 * `applyOptimisticQty`, exported for the same reason: every interesting decision in it
 * is testable without a request. Never rounds; the server returns authoritative strings.
 *
 * The component rows move too, because a combo is bought whole and a card whose header
 * says 2 over rows that still say 1 is worse than no optimism at all. Their per-unit
 * quantities are recovered from the CURRENT line (`quantity / oldComboQty`), which is
 * exact: the server derives them the same way (`line.quantity = comboQty x perBox`). */
export function applyOptimisticComboQty(cart: Cart, groupId: number, qty: number): Cart {
  const combos = (cart.combos ?? [])
    .map((c) => {
      if (c.group_id !== groupId) return c;
      if (qty <= 0) return null;
      const unit = Number(c.unit_price ?? "0");
      const perBoxDivisor = c.quantity || 1;
      const componentsUnit = Number(c.components_total ?? "0") / perBoxDivisor;
      return {
        ...c,
        quantity: qty,
        line_total: (unit * qty).toFixed(2),
        components_total: (componentsUnit * qty).toFixed(2),
        saving: (componentsUnit * qty - unit * qty).toFixed(2),
        items: c.items.map((line) => {
          const perBox = line.quantity / perBoxDivisor;
          const lineUnit = Number(line.unit_price ?? "0");
          return {
            ...line,
            quantity: perBox * qty,
            line_total: (lineUnit * perBox * qty).toFixed(2),
          };
        }),
      };
    })
    .filter((c): c is NonNullable<typeof c> => c !== null);

  const standalone = cart.items
    .filter((l) => !l.unavailable)
    .reduce((s, l) => s + Number(l.line_total ?? "0"), 0);
  const bundleList = combos
    .filter((c) => !c.unavailable)
    .reduce((s, c) => s + Number(c.components_total ?? "0"), 0);
  const saving = combos
    .filter((c) => !c.unavailable)
    .reduce((s, c) => s + Number(c.saving ?? "0"), 0);
  const subtotal = standalone + bundleList;
  return {
    ...cart,
    combos,
    subtotal: subtotal.toFixed(2),
    combo_discount: saving.toFixed(2),
    total: (subtotal - saving).toFixed(2),
  };
}

async function throwCartError(res: Response): Promise<never> {
  const body: { code?: string } | null = await res.json().catch(() => null);
  throw new CartRequestError(res.status, body?.code);
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
      if (!res.ok) await throwCartError(res);
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
      if (!res.ok) await throwCartError(res);
      return res.json() as Promise<Cart>;
    },
    onSuccess: (data) => qc.setQueryData(KEY, data),
  });

  const addCombo = useMutation({
    mutationFn: async (v: { comboSlug: string; quantity: number }) => {
      const res = await fetch("/api/cart/combos", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ combo_slug: v.comboSlug, quantity: v.quantity }),
      });
      if (!res.ok) await throwCartError(res);
      return res.json() as Promise<Cart>;
    },
    onSuccess: (data) => qc.setQueryData(KEY, data),
  });

  // Quantity and removal are ONE mutation because they are one server route: a combo is
  // bought whole, so 0 means "take the bundle out" rather than "empty a line inside it".
  const setComboQty = useMutation({
    mutationFn: async (v: { groupId: number; quantity: number }) => {
      const res = await fetch(`/api/cart/combos/${v.groupId}`, {
        method: v.quantity <= 0 ? "DELETE" : "PATCH",
        headers: { "content-type": "application/json" },
        ...(v.quantity <= 0 ? {} : { body: JSON.stringify({ quantity: v.quantity }) }),
      });
      if (!res.ok) await throwCartError(res);
      return res.json() as Promise<Cart>;
    },
    onMutate: async (v) => {
      await qc.cancelQueries({ queryKey: KEY });
      const prev = qc.getQueryData<Cart>(KEY);
      if (prev) qc.setQueryData(KEY, applyOptimisticComboQty(prev, v.groupId, v.quantity));
      return { prev };
    },
    onError: (_e, _v, ctx) => { if (ctx?.prev) qc.setQueryData(KEY, ctx.prev); },
    onSettled: (data) => { if (data) qc.setQueryData(KEY, data); },
  });

  return {
    cart: query.data ?? EMPTY_CART,
    isLoading: query.isLoading,
    addItem,
    setQty,
    addCombo,
    setComboQty,
  };
}
