"use client";
import {
  createContext, useCallback, useContext, useMemo, useState, type ReactNode,
} from "react";
import type { Variant } from "@/lib/catalog";
import { matchVariant, variantAxes } from "@/lib/variant-axes";

/**
 * Shared selected-variant state between the gallery (left column) and the buy box
 * (right column) — the two client islands of the PDP.
 *
 * ── WHY NOTHING IS PRE-SELECTED ANY MORE (2026-09-08) ───────────────────────────────
 *
 * Until now this pre-selected the first in-stock priced variant, so a product sold in
 * 80g/175g/275g opened on 80g with a price, a green "In stock" and a live Add to Cart.
 * Shoppers read that as "this is the product" and bought the first size without ever
 * noticing the picker — which is what the complaints were about. The picker now opens
 * on "SELECT PRODUCT SIZE" and the buy buttons ask for a choice before they do
 * anything.
 *
 * The one exception is a product with exactly ONE purchasable variant: there is no
 * choice to make, so making the shopper make it would be theatre. That covers every
 * single-variant product (the common case) and the rare multi-variant product where
 * only one variant is priced in the shopper's country.
 *
 * ── WHY SELECTIONS, NOT A VARIANT ───────────────────────────────────────────────────
 *
 * The state is a per-axis map, not a Variant. On a two-axis product (Size × Colour) a
 * single-Variant state cannot represent "size chosen, colour not yet" — picking a size
 * would have to land on a concrete variant, which silently picks a colour too: the same
 * bug one level down. The concrete variant is DERIVED, and only once every axis is
 * answered.
 */

/** The axis values a variant stands for, trimmed — the shape the selection map holds. */
export function optionSelections(variant: Variant): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [name, value] of Object.entries(variant.option_values ?? {})) {
    const trimmed = String(value).trim();
    if (trimmed) out[name] = trimmed;
  }
  return out;
}

/** Variants a shopper can actually buy here. An unpriced variant is not sold in this
 * country — the picker shows it as "Unavailable". */
export function purchasable(variants: Variant[]): Variant[] {
  return variants.filter((v) => v.price !== null);
}

/**
 * The variant the PDP may open on, or null when the shopper must choose.
 * Exactly one purchasable variant = nothing to choose; anything else = ask.
 */
export function initialVariant(variants: Variant[]): Variant | null {
  const priced = purchasable(variants);
  return priced.length === 1 ? priced[0] : null;
}

/** What the buy box is looking at right now. */
export type PdpStatus =
  /** A concrete, buyable-or-not variant is selected. */
  | "ready"
  /** Nothing is sold in this country — no variant carries a price. */
  | "unavailable"
  /** Every axis is answered but no variant carries that combination (defensive: the
   *  picker disables combinations that cannot resolve). */
  | "no-match"
  /** The shopper still owes us an answer on at least one axis. */
  | "choose";

interface PdpState {
  /** The concrete variant, or null while the choice is incomplete. */
  variant: Variant | null;
  selections: Record<string, string>;
  /** Answer one axis. Other axes are kept when they can still coexist, and dropped
   *  when they cannot — never silently changed to something the shopper did not pick. */
  select: (axis: string, value: string) => void;
  /** Pick a whole variant directly (products whose variants carry no option data). */
  setVariant: (v: Variant) => void;
  qty: number;
  setQty: (n: number) => void;
  status: PdpStatus;
  /** Bumped when something (a buy button) needs the shopper to answer the picker.
   *  The picker watches it: opens the first unanswered axis and marks it invalid. */
  promptNonce: number;
  promptChoice: () => void;
}
const Ctx = createContext<PdpState | null>(null);

interface Selection {
  selections: Record<string, string>;
  /** Set only for a direct whole-variant pick (a product whose variants carry no
   *  option data, or the lone purchasable variant we opened on). Cleared by any axis
   *  pick. Held as an ID, not the Variant: `router.refresh()` (which Add to Cart does
   *  on a "just sold out") hands down a fresh variants array, and a stored object
   *  would keep insisting the thing is in stock at yesterday's price. */
  direct: number | null;
}

export function PdpProvider({ variants, children }: { variants: Variant[]; children: ReactNode }) {
  const axes = useMemo(() => variantAxes(variants), [variants]);
  const [sel, setSel] = useState<Selection>(() => {
    const v = initialVariant(variants);
    return { selections: v ? optionSelections(v) : {}, direct: v?.id ?? null };
  });
  const [qty, setQty] = useState(1);
  const [promptNonce, setPromptNonce] = useState(0);

  const complete = axes.length > 0 && axes.every((a) => sel.selections[a.name]);
  const derived = complete ? matchVariant(variants, sel.selections) : null;
  const direct = sel.direct === null
    ? null
    : variants.find((v) => v.id === sel.direct) ?? null;
  const variant = direct ?? derived;

  const select = useCallback((axis: string, value: string) => {
    setSel((prev) => {
      const next: Record<string, string> = { [axis]: value };
      // Keep the other answers that can still coexist with this one; drop the rest.
      // Dropping asks the question again — the alternative is answering it for them.
      for (const a of axes) {
        if (a.name === axis) continue;
        const held = prev.selections[a.name];
        if (held && matchVariant(variants, { ...next, [a.name]: held })) next[a.name] = held;
      }
      return { selections: next, direct: null };
    });
  }, [axes, variants]);

  const setVariant = useCallback((v: Variant) => {
    setSel({ selections: optionSelections(v), direct: v.id });
  }, []);

  const promptChoice = useCallback(() => setPromptNonce((n) => n + 1), []);

  const status: PdpStatus = variant
    ? "ready"
    : purchasable(variants).length === 0
      ? "unavailable"
      : complete
        ? "no-match"
        : "choose";

  const value = useMemo(
    () => ({
      variant, selections: sel.selections, select, setVariant,
      qty, setQty, status, promptNonce, promptChoice,
    }),
    [variant, sel.selections, select, setVariant, qty, status, promptNonce, promptChoice],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function usePdp(): PdpState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("usePdp must be used inside PdpProvider");
  return ctx;
}
