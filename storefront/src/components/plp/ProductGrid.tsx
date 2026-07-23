import type { ProductCard as ProductCardData } from "@/lib/catalog";
import { ProductCard } from "@/components/product/ProductCard";

export function ProductGrid({ products }: { products: ProductCardData[] }) {
  if (products.length === 0) {
    return (
      <div className="rounded-[var(--radius-card)] bg-beige px-6 py-16 text-center">
        <p className="font-display text-xl">Nothing matches those filters.</p>
        <p className="mt-2 text-sm text-muted">Try widening the price range or clearing filters.</p>
      </div>
    );
  }
  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-4">
      {products.map((p, i) => <ProductCard key={p.slug} product={p} priority={i < 4} />)}
    </div>
  );
}
