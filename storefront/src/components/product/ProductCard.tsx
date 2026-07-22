import Image from "next/image";
import Link from "next/link";
import type { ProductCard as ProductCardData } from "@/lib/catalog";
import { mediaUrl } from "@/lib/media";
import { PriceTag } from "@/components/product/PriceTag";
import { ReviewStars } from "@/components/product/ReviewStars";
import { WishlistHeart } from "@/components/product/WishlistHeart";

/** The one product card. Hover: image swaps to hover_image (pure CSS, no JS), the
 * artwork zooms gently, and the whole card lifts — the calm, "expensive" motion
 * vocabulary from design-direction.md. Gold "Bestseller" badge for featured
 * products (gold = seasoning). NOTE: the list API's `brand` field is the brand
 * SLUG (SlugRelatedField) — title-case it for display. */
function brandLabel(slug: string): string {
  return slug
    .split("-")
    .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w))
    .join(" ");
}

export function ProductCard({
  product,
  priority = false,
}: {
  product: ProductCardData;
  priority?: boolean;
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
            <span className="absolute left-3 top-3 rounded-full bg-gold/90 px-2.5 py-0.5 text-xs font-medium tracking-wide text-surface shadow-sm">
              Bestseller
            </span>
          )}
        </div>
        <div className="space-y-1.5 p-4">
          {product.brand && (
            <p className="text-xs uppercase tracking-wide text-muted">
              {brandLabel(product.brand)}
            </p>
          )}
          <h3 className="font-display text-base leading-snug">{product.name}</h3>
          <ReviewStars rating={product.rating_avg} count={product.rating_count} />
          {product.from_price && (
            <PriceTag amount={product.from_price} currency={product.currency} from />
          )}
        </div>
      </Link>
    </div>
  );
}
