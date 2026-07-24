"use client";
import type { ProductDetail } from "@/lib/catalog";
import { PriceTag } from "@/components/product/PriceTag";
import { ReviewStars } from "@/components/product/ReviewStars";
import { VariantPicker } from "@/components/product/VariantPicker";
import { QtySelector } from "@/components/product/QtySelector";
import { usePdp } from "@/components/product/PdpContext";

export function BuyBox({ product, deliveryLine }: {
  product: ProductDetail; deliveryLine: string;
}) {
  const { variant } = usePdp();
  const price = variant?.price ?? null;
  return (
    <div className="rounded-[var(--radius-card)] bg-surface p-6 shadow-sm lg:sticky lg:top-24">
      {product.brand && (
        <p className="text-xs uppercase tracking-wide text-muted">{product.brand.name}</p>
      )}
      <h1 className="mt-1 font-display text-3xl leading-tight">{product.name}</h1>
      <div className="mt-2">
        <ReviewStars rating={product.rating_avg} count={product.rating_count} />
      </div>
      {price ? (
        <div className="mt-4">
          <PriceTag amount={price.amount} compareAt={price.compare_at} currency={price.currency} size="lg" />
        </div>
      ) : (
        <p className="mt-4 text-muted">Currently unavailable in your region.</p>
      )}
      <VariantPicker variants={product.variants} />
      {variant && (
        <p className="mt-4 text-sm" aria-live="polite">
          {!variant.in_stock
            ? <span className="font-medium text-muted">Out of stock</span>
            : variant.low_stock
              ? <span className="font-medium text-gold">Only a few left</span>
              : <span className="font-medium text-accent">In stock</span>}
        </p>
      )}
      <p className="mt-3 flex items-start gap-2 text-sm text-muted">
        <span aria-hidden>🚚</span>{deliveryLine}
      </p>
      <QtySelector />
      <div className="mt-6 space-y-3">
        {/* onClick wiring lands in Task 12 (cart-ui event + buy-now BFF). */}
        <button type="button" disabled data-task12="buy-now"
          className="w-full rounded-full bg-accent py-3.5 font-medium text-surface transition-colors hover:bg-accent-strong disabled:opacity-50">
          Buy Now
        </button>
        <button type="button" disabled data-task12="add-to-cart"
          className="w-full rounded-full border border-accent py-3.5 font-medium text-accent transition-colors hover:bg-accent/5 disabled:opacity-50">
          Add to Cart
        </button>
      </div>
      <p className="mt-4 text-center text-xs text-muted">Secure worldwide checkout · 14-day returns</p>
    </div>
  );
}
