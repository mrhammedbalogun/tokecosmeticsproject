import Link from "next/link";
import type { ProductCard as ProductCardData } from "@/lib/catalog";
import { ProductCard } from "@/components/product/ProductCard";
import { Carousel } from "@/components/home/Carousel";
import { FadeUp } from "@/components/motion/Motion";

/** Sections 7 ("Best sellers", carousel) and 9 ("New arrivals", grid). Server
 * component — the product data is fetched on the page and passed in; the only
 * client island is the Carousel shell (and the wishlist heart inside each card).
 * Renders nothing when there are no products so an empty seeded collection never
 * leaves a bare heading. */
export function ProductRow({
  title,
  products,
  href,
  carousel = false,
}: {
  title: string;
  products: ProductCardData[];
  href: string;
  carousel?: boolean;
}) {
  if (products.length === 0) return null;
  const cards = products.map((p) => (
    <div key={p.slug} className={carousel ? "w-[70vw] shrink-0 snap-start sm:w-72" : ""}>
      <ProductCard product={p} />
    </div>
  ));
  return (
    <section aria-label={title} className="mx-auto max-w-7xl px-4 py-16">
      <FadeUp>
        <div className="flex items-end justify-between gap-4">
          <h2 className="font-display text-3xl md:text-4xl">{title}</h2>
          <Link
            href={href}
            className="shrink-0 text-sm font-medium text-accent transition-colors hover:text-accent-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            View all →
          </Link>
        </div>
      </FadeUp>
      <div className="mt-8">
        {carousel ? (
          <Carousel label={title}>{cards}</Carousel>
        ) : (
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">{cards}</div>
        )}
      </div>
    </section>
  );
}
