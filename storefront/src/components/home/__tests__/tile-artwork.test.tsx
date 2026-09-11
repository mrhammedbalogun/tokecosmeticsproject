import { describe, it, expect, vi } from "vitest";
import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { CmsBanner } from "@/lib/cms";
import { isArtwork } from "@/components/home/TileMedia";
import { TrioSection } from "@/components/home/TrioSection";
import { TikTokSection } from "@/components/home/TikTokSection";
import { FeatureSplit } from "@/components/home/FeatureSplit";

/**
 * `image_mode` on the homepage TILES (2026-09-11), which is not the same promise the
 * hero makes. A tile's shape is fixed by the grid it sits in, so artwork mode here means
 * only "the shop writes nothing over it" — the picture still fills the slot.
 */
const banner = (over: Partial<CmsBanner> = {}): CmsBanner => ({
  id: 1,
  title: "Kids Term Kit",
  subtitle: "",
  image: "https://cdn/catalog/library/art.png",
  mobile_image: null,
  cta_text: "",
  cta_url: "",
  video_url: "",
  video_mode: "loop",
  image_mode: "overlay",
  tagline: "Tagline the shop writes",
  placement: "trio",
  sort: 0,
  ...over,
});

// TikTokSection renders ProductCards beside the panel; those islands want a router and
// a QueryClient, exactly as ProductRow.test.tsx sets up.
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

const product = (slug: string) =>
  ({ slug, name: slug, price: "1000", currency: "NGN", image: null }) as never;

function renderWithQuery(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(ui, {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    ),
  });
}

describe("isArtwork", () => {
  it("is false without artwork — suppressing our copy would leave an empty tile", () => {
    expect(isArtwork(banner({ image_mode: "artwork", image: null }))).toBe(false);
    expect(isArtwork(banner({ image_mode: "artwork" }))).toBe(true);
    expect(isArtwork(banner())).toBe(false);
    expect(isArtwork(null)).toBe(false);
  });
});

describe("TrioSection", () => {
  // The section always renders three tiles; one CMS banner replaces the first and the
  // other two keep their built-in copy, so counts are what distinguish the modes.
  it("writes its own heading, tagline and button over an overlay photo", () => {
    render(<TrioSection banners={[banner()]} />);
    expect(screen.getByRole("heading", { name: "Kids Term Kit" })).not.toHaveClass("sr-only");
    expect(screen.getByText("Tagline the shop writes")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Explore" })).toHaveLength(3);
  });

  it("writes nothing over a finished piece, and makes the whole tile the link", () => {
    render(<TrioSection banners={[banner({ image_mode: "artwork", cta_url: "/promo" })]} />);
    expect(screen.queryByText("Tagline the shop writes")).toBeNull();
    // Its own Explore button is gone; the two untouched tiles keep theirs.
    expect(screen.getAllByRole("link", { name: "Explore" })).toHaveLength(2);
    const link = screen.getByRole("link", { name: "Kids Term Kit" });
    expect(link).toHaveAttribute("href", "/promo");
    // The heading survives for the outline and for anyone who cannot read the pixels.
    expect(screen.getByRole("heading", { name: "Kids Term Kit" })).toHaveClass("sr-only");
  });

  it("falls back to the tile's own destination — a tile always has somewhere to go", () => {
    render(<TrioSection banners={[banner({ image_mode: "artwork" })]} />);
    expect(screen.getByRole("link", { name: "Kids Term Kit" })).toHaveAttribute(
      "href",
      "/products?collection=babies",
    );
  });
});

describe("TikTokSection", () => {
  it("suppresses its copy for a finished piece and links the whole panel", () => {
    renderWithQuery(
      <TikTokSection
        products={[product("a"), product("b")]}
        banner={banner({ placement: "tiktok", image_mode: "artwork", title: "On Your Feed" })}
      />,
    );
    expect(screen.queryByText(/community favourites/)).toBeNull();
    expect(screen.queryByRole("link", { name: "Shop Now" })).toBeNull();
    expect(screen.getByRole("link", { name: "On Your Feed" })).toBeInTheDocument();
  });
});

describe("FeatureSplit", () => {
  it("honours artwork on the Glow Set tile", () => {
    render(<FeatureSplit banners={[banner({ placement: "feature", image_mode: "artwork" })]} />);
    expect(screen.queryByText(/community swears by/)).toBeNull();
    expect(screen.getByRole("link", { name: "Kids Term Kit" })).toBeInTheDocument();
  });

  it("IGNORES artwork on the two small tiles, whose copy block is their only height", () => {
    // TileMedia is absolutely positioned: remove the text from these and the tile
    // collapses to zero height below `lg`. They are excluded in the admin too.
    render(
      <FeatureSplit
        banners={[
          banner({ id: 2, placement: "feature_nature", image_mode: "artwork", title: "Nature" }),
          banner({ id: 3, placement: "feature_collection", image_mode: "artwork", title: "Naturals" }),
        ]}
      />,
    );
    expect(screen.getByRole("heading", { name: "Nature" })).not.toHaveClass("sr-only");
    expect(screen.getByRole("heading", { name: "Naturals" })).not.toHaveClass("sr-only");
  });
});
