"use client";
import type { ProductDetail, Variant } from "@/lib/catalog";
import { PriceTag } from "@/components/product/PriceTag";
import { ReviewStars } from "@/components/product/ReviewStars";
import { VariantPicker } from "@/components/product/VariantPicker";
import { QtySelector } from "@/components/product/QtySelector";
import { BuyButtons } from "@/components/product/BuyButtons";
import { PdpWishlistButton } from "@/components/product/PdpWishlistButton";
import { purchasable, usePdp } from "@/components/product/PdpContext";

/** What the price line says before a choice is made: the cheapest thing on offer,
 * prefixed "from" only when the options actually differ in price. A blanket "from" on a
 * product whose sizes all cost the same reads as a hidden extra. */
function openingPrice(variants: Variant[]): { amount: string; currency: string; from: boolean } | null {
  const priced = purchasable(variants);
  if (priced.length === 0) return null;
  const cheapest = priced.reduce((a, b) =>
    Number(a.price!.amount) <= Number(b.price!.amount) ? a : b);
  return {
    amount: cheapest.price!.amount,
    currency: cheapest.price!.currency,
    from: priced.some((v) => v.price!.amount !== cheapest.price!.amount),
  };
}

export function BuyBox({ product, deliveryLine }: {
  product: ProductDetail; deliveryLine: string;
}) {
  const { variant, status } = usePdp();
  const price = variant?.price ?? null;
  const opening = price ? null : openingPrice(product.variants);
  return (
    <div className="rounded-[var(--radius-card)] bg-surface p-6 shadow-sm lg:sticky lg:top-24">
      {product.brand && (
        <p className="text-xs uppercase tracking-wide text-muted">{product.brand.name}</p>
      )}
      <h1 className="mt-1 font-display text-3xl leading-tight">{product.name}</h1>
      <div className="mt-2">
        {product.rating_count > 0 ? (
          <a href="#reviews" className="inline-block transition-opacity hover:opacity-80">
            <ReviewStars rating={product.rating_avg} count={product.rating_count} />
          </a>
        ) : (
          <a href="#reviews" className="text-sm text-muted underline-offset-2 hover:underline">
            Be the first to review
          </a>
        )}
      </div>
      {price ? (
        <div className="mt-4">
          <PriceTag amount={price.amount} compareAt={price.compare_at} currency={price.currency} size="lg" />
        </div>
      ) : opening ? (
        /* Nothing chosen yet — show what the product starts at rather than a blank or,
           worse, "unavailable", which is what this branch used to say. */
        <div className="mt-4">
          <PriceTag amount={opening.amount} currency={opening.currency} from={opening.from} size="lg" />
        </div>
      ) : (
        <p className="mt-4 text-muted">Currently unavailable in your region.</p>
      )}
      <VariantPicker variants={product.variants} />
      {status === "no-match" && (
        <p role="alert" className="mt-4 text-sm text-red-700">
          That combination isn&apos;t available — try another.
        </p>
      )}
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
      <PdpWishlistButton name={product.name} variants={product.variants} />
      <p className="mt-4 text-center text-xs text-muted">Secure worldwide checkout</p>
    </div>
  );
}
