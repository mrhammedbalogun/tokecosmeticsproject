import { describe, it, expect, vi } from "vitest";
import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import { FeaturedCategories } from "@/components/home/FeaturedCategories";
import type { CategoryNode } from "@/lib/catalog";

// Stub the FadeUp scroll-reveal island so tests assert plain DOM output, not
// framer-motion behaviour.
vi.mock("@/components/motion/Motion", () => ({
  FadeUp: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));

function cat(slug: string, image: string | null = null): CategoryNode {
  return { name: slug, slug, image, sort_order: 0, children: [] };
}

describe("FeaturedCategories", () => {
  it("renders nothing for an empty category tree", () => {
    const { container } = render(<FeaturedCategories categories={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders a beige-disc fallback with no <img> when a category has no image", () => {
    render(<FeaturedCategories categories={[cat("face", null)]} />);
    expect(screen.getByRole("link", { name: /face/i })).toHaveAttribute(
      "href",
      "/category/face",
    );
    expect(screen.queryByRole("img")).toBeNull();
  });

  it("shows at most the first six roots (slice 0,6)", () => {
    const many = Array.from({ length: 8 }, (_, i) => cat(`cat-${i}`));
    render(<FeaturedCategories categories={many} />);
    expect(screen.getAllByRole("link")).toHaveLength(6);
  });
});
