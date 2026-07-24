import type { ProductCard as ProductCardData } from "@/lib/catalog";
import { ProductCard } from "@/components/product/ProductCard";
import { Carousel } from "@/components/home/Carousel";

export function RelatedProducts({ products }: { products: ProductCardData[] }) {
  if (products.length === 0) return null;
  return (
    <section aria-label="You may also like" className="mt-16">
      <h2 className="font-display text-2xl">You may also like</h2>
      <div className="mt-6">
        <Carousel label="Related products">
          {products.map((p) => (
            <div key={p.slug} className="w-[60vw] shrink-0 snap-start sm:w-64">
              <ProductCard product={p} />
            </div>
          ))}
        </Carousel>
      </div>
    </section>
  );
}
