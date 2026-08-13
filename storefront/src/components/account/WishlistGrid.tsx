"use client";

/**
 * The account wishlist grid (Plan-15d Task 3). Same no-optimistic-state ruling as
 * AddressBook: a successful Remove re-GETs /api/wishlist and replaces the list
 * wholesale rather than splicing the removed item out locally. Add-to-cart mirrors
 * the PDP's Add to Cart exactly (BuyButtons.addToCart): addItem.mutateAsync then
 * openCartDrawer().
 *
 * The cards' hearts read the shared ["wishlist"] cache (useWishlist), so a Remove
 * here must invalidate that cache or the heart on the same card keeps showing
 * "saved". (This supersedes the earlier "don't sync heart and grid" ruling — the
 * shared cache made the sync free.)
 */
import Link from "next/link";
import { useState } from "react";
import type { ProductCard as ProductCardData } from "@/lib/catalog";
import { ProductCard } from "@/components/product/ProductCard";
import { isJustSoldOut, useCart } from "@/hooks/useCart";
import { useWishlist } from "@/hooks/useWishlist";
import { openCartDrawer } from "@/lib/cart-ui";

export interface WishlistItem {
  sku: string;
  product: ProductCardData | null;
  created_at: string;
}

const ADD_ERROR = "Couldn't add to cart — try again.";
const SOLD_OUT_ERROR = "Just sold out — no longer available.";
const REMOVE_ERROR = "Couldn't remove — try again.";

function omit(rec: Record<string, string>, sku: string): Record<string, string> {
  const next = { ...rec };
  delete next[sku];
  return next;
}

export function WishlistGrid({ initial }: { initial: WishlistItem[] }) {
  const [items, setItems] = useState<WishlistItem[]>(initial);
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const { addItem } = useCart();
  const { invalidate: invalidateHearts } = useWishlist();

  async function refresh() {
    const res = await fetch("/api/wishlist");
    if (res.ok) {
      const data: WishlistItem[] = await res.json().catch(() => []);
      setItems(data);
    }
  }

  async function handleAddToBag(sku: string, variantId: number) {
    setBusy((prev) => ({ ...prev, [sku]: true }));
    setErrors((prev) => omit(prev, sku));
    try {
      await addItem.mutateAsync({ variantId, quantity: 1 });
      openCartDrawer();
    } catch (err) {
      setErrors((prev) => ({ ...prev, [sku]: isJustSoldOut(err) ? SOLD_OUT_ERROR : ADD_ERROR }));
      if (isJustSoldOut(err)) void refresh(); // re-pull the list so the card shows Sold Out
    } finally {
      setBusy((prev) => ({ ...prev, [sku]: false }));
    }
  }

  async function handleRemove(sku: string) {
    setBusy((prev) => ({ ...prev, [sku]: true }));
    setErrors((prev) => omit(prev, sku));
    try {
      const res = await fetch(`/api/wishlist/${encodeURIComponent(sku)}`, { method: "DELETE" });
      if (!res.ok) {
        setErrors((prev) => ({ ...prev, [sku]: REMOVE_ERROR }));
        return;
      }
      await refresh();
      invalidateHearts();
    } catch {
      setErrors((prev) => ({ ...prev, [sku]: REMOVE_ERROR }));
    } finally {
      setBusy((prev) => ({ ...prev, [sku]: false }));
    }
  }

  if (items.length === 0) {
    return (
      <div>
        <p className="text-sm text-muted">Your wishlist is empty.</p>
        <Link
          href="/products"
          className="mt-3 inline-block text-sm font-medium text-accent underline hover:text-accent-strong"
        >
          Browse products
        </Link>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-4">
      {items.map((item) => (
        <WishlistCard
          key={item.sku}
          item={item}
          busy={Boolean(busy[item.sku])}
          error={errors[item.sku]}
          onAddToBag={(variantId) => handleAddToBag(item.sku, variantId)}
          onRemove={() => handleRemove(item.sku)}
        />
      ))}
    </div>
  );
}

function WishlistCard({
  item, busy, error, onAddToBag, onRemove,
}: {
  item: WishlistItem;
  busy: boolean;
  error?: string;
  onAddToBag: (variantId: number) => void;
  onRemove: () => void;
}) {
  if (!item.product) {
    return (
      <div className="rounded-[var(--radius-card)] border border-line p-4 text-muted">
        <p className="text-sm">No longer available</p>
        <p className="mt-1 text-xs">{item.sku}</p>
        <button
          type="button"
          onClick={onRemove}
          disabled={busy}
          className="mt-3 text-sm text-red-700 underline hover:text-red-800 disabled:opacity-50"
        >
          Remove
        </button>
        {error && (
          <p role="alert" className="mt-2 text-sm text-red-700">{error}</p>
        )}
      </div>
    );
  }

  const { product } = item;

  return (
    <div>
      <ProductCard product={product} />
      <div className="mt-2 space-y-2">
        {product.default_variant_id !== null ? (
          <button
            type="button"
            onClick={() => onAddToBag(product.default_variant_id!)}
            disabled={busy}
            className="w-full rounded-full bg-accent px-3 py-2 text-sm text-surface transition-colors hover:bg-accent-strong disabled:opacity-50"
          >
            {busy ? "Adding…" : "Add to Cart"}
          </button>
        ) : (
          <div>
            <button
              type="button"
              disabled
              className="w-full rounded-full bg-accent px-3 py-2 text-sm text-surface opacity-50"
            >
              Add to Cart
            </button>
            <p className="mt-1 text-xs text-muted">Not available in your region</p>
          </div>
        )}
        <button
          type="button"
          onClick={onRemove}
          disabled={busy}
          className="w-full text-sm text-red-700 underline hover:text-red-800 disabled:opacity-50"
        >
          Remove
        </button>
        {error && (
          <p role="alert" className="text-sm text-red-700">{error}</p>
        )}
      </div>
    </div>
  );
}
