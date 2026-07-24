import { describe, it, expect, vi } from "vitest";
import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import { ProductRow } from "@/components/home/ProductRow";
import type { ProductCard as ProductCardData } from "@/lib/catalog";

vi.mock("@/components/motion/Motion", () => ({
  FadeUp: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));
// ProductCard -> WishlistHeart island calls useRouter().
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

function make(slug: string): ProductCardData {
  return {
    name: `Product ${slug}`,
    slug,
    brand: "toke-naturals",
    is_featured: false,
    from_price: "10000.00",
    currency: "NGN",
    image: "/media/p.png",
    hover_image: null,
    default_variant_id: 1,
    default_sku: `SKU-${slug}`,
    rating_avg: "0.00",
    rating_count: 0,
  };
}

describe("ProductRow", () => {
  it("renders nothing when there are no products", () => {
    const { container } = render(
      <ProductRow title="Best sellers" products={[]} href="/products" />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders the title, a View all link, and one card per product", () => {
    render(
      <ProductRow title="New arrivals" products={[make("a"), make("b")]} href="/products?ordering=newest" />,
    );
    expect(screen.getByRole("heading", { name: "New arrivals" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /view all/i })).toHaveAttribute(
      "href",
      "/products?ordering=newest",
    );
    expect(screen.getByRole("heading", { name: "Product a" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Product b" })).toBeInTheDocument();
  });

  it("wraps cards in a labelled carousel group only in carousel mode", () => {
    const { rerender } = render(
      <ProductRow title="Best sellers" products={[make("a")]} href="/x" carousel />,
    );
    expect(screen.getByRole("group", { name: "Best sellers" })).toBeInTheDocument();
    rerender(<ProductRow title="Best sellers" products={[make("a")]} href="/x" />);
    expect(screen.queryByRole("group", { name: "Best sellers" })).toBeNull();
  });
});
