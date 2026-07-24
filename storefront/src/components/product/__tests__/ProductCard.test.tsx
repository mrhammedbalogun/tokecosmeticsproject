import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ProductCard } from "@/components/product/ProductCard";
import type { ProductCard as ProductCardData } from "@/lib/catalog";

// ProductCard embeds the WishlistHeart client island, which calls useRouter().
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

function make(overrides: Partial<ProductCardData> = {}): ProductCardData {
  return {
    name: "Radiance Glow Serum",
    slug: "radiance-glow-serum",
    brand: "toke-naturals",
    is_featured: false,
    from_price: "18500.00",
    currency: "NGN",
    image: "/media/catalog/products/serum.png",
    hover_image: null,
    default_variant_id: 1,
    default_sku: "TOKE-SERUM-50",
    rating_avg: "0.00",
    rating_count: 0,
    ...overrides,
  };
}

describe("ProductCard", () => {
  it("renders only the primary image when hover_image is null (no second/broken img)", () => {
    render(<ProductCard product={make({ hover_image: null })} />);
    // The hover <Image> has alt="" (role=presentation), so an accessible image
    // query returns exactly the primary product image — none is left broken.
    const imgs = screen.getAllByRole("img");
    expect(imgs).toHaveLength(1);
    expect(screen.getByRole("img", { name: "Radiance Glow Serum" })).toBeInTheDocument();
  });

  it("title-cases the brand slug and links to the product", () => {
    render(<ProductCard product={make()} />);
    expect(screen.getByText("Toke Naturals")).toBeInTheDocument();
    expect(screen.getByRole("link")).toHaveAttribute("href", "/product/radiance-glow-serum");
  });

  it("shows the gold Bestseller badge only for featured products", () => {
    const { rerender } = render(<ProductCard product={make({ is_featured: false })} />);
    expect(screen.queryByText("Bestseller")).toBeNull();
    rerender(<ProductCard product={make({ is_featured: true })} />);
    expect(screen.getByText("Bestseller")).toBeInTheDocument();
  });
});
