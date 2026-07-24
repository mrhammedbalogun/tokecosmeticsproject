"use client";
import type { ProductDetail } from "@/lib/catalog";
import { PriceTag } from "@/components/product/PriceTag";
import { ReviewStars } from "@/components/product/ReviewStars";
import { VariantPicker } from "@/components/product/VariantPicker";
import { QtySelector } from "@/components/product/QtySelector";
import { BuyButtons } from "@/components/product/BuyButtons";
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
      <BuyButtons />
      <p className="mt-4 text-center text-xs text-muted">Secure worldwide checkout · 14-day returns</p>
    </div>
  );
}
