import Image from "next/image";
import Link from "next/link";
import type { ProductCard as ProductCardData } from "@/lib/catalog";
import { mediaUrl } from "@/lib/media";
import { PriceTag } from "@/components/product/PriceTag";
import { ReviewStars } from "@/components/product/ReviewStars";
import { WishlistHeart } from "@/components/product/WishlistHeart";
import { CardAddButton } from "@/components/product/CardAddButton";

/** The one product card. Hover: image swaps to hover_image (pure CSS, no JS), the
 * artwork zooms gently, and the whole card lifts — the calm, "expensive" motion
 * vocabulary from design-direction.md. Gold "Bestseller" badge for featured
 * products (gold = seasoning). NOTE: the list API's `brand` field is the brand
 * SLUG (SlugRelatedField) — title-case it for display. */
/** Replaces the Add to Cart button when the product has no sellable stock in the
 * shopper's country (in_stock === false; missing field = old cached payload, assume
 * in stock). Same pill dimensions as the button so card footers stay aligned. */
function SoldOutTag() {
  return (
    <span className="whitespace-nowrap rounded-full border border-line px-3.5 py-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">
      Sold Out
    </span>
  );
}

function brandLabel(slug: string): string {
  return slug
    .split("-")
    .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w))
    .join(" ");
}

export function ProductCard({
  product,
  priority = false,
  compact = false,
}: {
  product: ProductCardData;
  priority?: boolean;
  /** Landing-page card (approved 2026-08-04): tall image, slim footer — one-line
   * name + price + one-click Add. No brand line, no stars; those live on the PDP. */
  compact?: boolean;
}) {
  const img = mediaUrl(product.image);
  const hover = mediaUrl(product.hover_image);
  return (
    <div className="group relative">
      <WishlistHeart sku={product.default_sku} name={product.name} />
      <Link
        href={`/product/${product.slug}`}
        className="block overflow-hidden rounded-[var(--radius-card)] border border-line/60 bg-surface shadow-sm transition-all duration-300 ease-out hover:-translate-y-1 hover:border-line hover:shadow-md focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        <div className="relative aspect-[3/4] overflow-hidden bg-beige">
          {img && (
            <Image
              src={img}
              alt={product.name}
              fill
              priority={priority}
              sizes="(max-width: 640px) 50vw, (max-width: 1024px) 33vw, 25vw"
              className={`object-cover transition-all duration-500 ease-out group-hover:scale-[1.04] ${
                hover ? "group-hover:opacity-0" : ""
              }`}
            />
          )}
          {hover && (
            <Image
              src={hover}
              alt=""
              aria-hidden
              fill
              sizes="(max-width: 640px) 50vw, (max-width: 1024px) 33vw, 25vw"
              className="object-cover opacity-0 transition-all duration-500 ease-out group-hover:scale-[1.04] group-hover:opacity-100"
            />
          )}
          {product.is_featured && (
            <span className="absolute left-3 top-3 rounded-full bg-gold px-2.5 py-0.5 text-xs font-medium tracking-wide text-foreground shadow-sm">
              Bestseller
            </span>
          )}
        </div>
        {compact ? (
          <div className="p-3">
            <h3 className="truncate text-[13px] font-semibold leading-tight">{product.name}</h3>
            <div className="mt-1.5 flex flex-wrap items-center justify-between gap-2">
              {product.from_price ? (
                <PriceTag amount={product.from_price} currency={product.currency} from />
              ) : (
                <span />
              )}
              {product.in_stock === false ? (
                <SoldOutTag />
              ) : (
                <CardAddButton
                  variantId={product.default_variant_id}
                  name={product.name}
                  slug={product.slug}
                  sku={product.default_sku}
                  price={product.from_price}
                  currency={product.currency}
                />
              )}
            </div>
          </div>
        ) : (
          <div className="space-y-1.5 p-4">
            {product.brand && (
              <p className="text-xs uppercase tracking-wide text-muted">
                {brandLabel(product.brand)}
              </p>
            )}
            <h3 className="font-display text-base leading-snug">{product.name}</h3>
            <ReviewStars rating={product.rating_avg} count={product.rating_count} />
            <div className="flex flex-wrap items-center justify-between gap-2 pt-0.5">
              {product.from_price ? (
                <PriceTag amount={product.from_price} currency={product.currency} from />
              ) : (
                <span />
              )}
              {product.in_stock === false ? (
                <SoldOutTag />
              ) : (
                <CardAddButton
                  variantId={product.default_variant_id}
                  name={product.name}
                  slug={product.slug}
                  sku={product.default_sku}
                  price={product.from_price}
                  currency={product.currency}
                />
              )}
            </div>
          </div>
        )}
      </Link>
    </div>
  );
}
