"use client";
import { usePdp } from "@/components/product/PdpContext";

const MAX_QTY = 10; // UI cap; the server re-caps against real stock on add

export function QtySelector() {
  const { qty, setQty } = usePdp();
  return (
    <div className="mt-5 inline-flex items-center rounded-full border border-line">
      <button type="button" aria-label="Decrease quantity" disabled={qty <= 1}
        onClick={() => setQty(Math.max(1, qty - 1))}
        className="px-4 py-2 text-lg disabled:opacity-30">−</button>
      <span aria-live="polite" className="w-10 text-center text-sm font-medium">{qty}</span>
      <button type="button" aria-label="Increase quantity" disabled={qty >= MAX_QTY}
        onClick={() => setQty(Math.min(MAX_QTY, qty + 1))}
        className="px-4 py-2 text-lg disabled:opacity-30">+</button>
    </div>
  );
}
