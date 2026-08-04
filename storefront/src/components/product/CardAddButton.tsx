"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { useCart } from "@/hooks/useCart";
import { openCartDrawer } from "@/lib/cart-ui";

/** One-click Add on a landing card (approved design). Single-variant products add
 * their default variant and open the drawer — the shortest path from homepage to
 * bag. Multi-variant products (no default_variant_id) route to the PDP instead:
 * silently picking a shade for someone is worse than one extra click.
 *
 * Inside the card's <Link>, so every event must stop propagation or the card
 * navigation swallows the click. */
export function CardAddButton({
  variantId,
  name,
  slug,
}: {
  variantId: number | null;
  name: string;
  slug: string;
}) {
  const { addItem } = useCart();
  const router = useRouter();
  const [busy, setBusy] = useState(false);

  async function onClick(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    if (variantId === null) {
      router.push(`/product/${slug}`);
      return;
    }
    setBusy(true);
    try {
      await addItem.mutateAsync({ variantId, quantity: 1 });
      openCartDrawer();
    } catch {
      // The drawer never opened and nothing changed — the PDP has the full,
      // explained add flow, so fail toward it rather than toward a dead button.
      router.push(`/product/${slug}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy}
      aria-label={`Add ${name} to bag`}
      className="rounded-full border border-line bg-surface px-3.5 py-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] transition-colors hover:border-accent hover:bg-accent hover:text-surface disabled:opacity-50"
    >
      {busy ? "…" : "Add"}
    </button>
  );
}
