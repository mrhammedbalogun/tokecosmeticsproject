"use client";
import { createContext, useContext, useState, type ReactNode } from "react";
import type { Variant } from "@/lib/catalog";

/** Shared selected-variant state between the gallery (left column) and the buy box
 * (right column) — the two client islands of the PDP. */
export function initialVariant(variants: Variant[]): Variant | null {
  const priced = variants.filter((v) => v.price !== null);
  return priced.find((v) => v.in_stock) ?? priced[0] ?? null;
}

interface PdpState {
  variant: Variant | null;
  setVariant: (v: Variant) => void;
  qty: number;
  setQty: (n: number) => void;
}
const Ctx = createContext<PdpState | null>(null);

export function PdpProvider({ variants, children }: { variants: Variant[]; children: ReactNode }) {
  const [variant, setVariant] = useState<Variant | null>(() => initialVariant(variants));
  const [qty, setQty] = useState(1);
  return <Ctx.Provider value={{ variant, setVariant, qty, setQty }}>{children}</Ctx.Provider>;
}

export function usePdp(): PdpState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("usePdp must be used inside PdpProvider");
  return ctx;
}
