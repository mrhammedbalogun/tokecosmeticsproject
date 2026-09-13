import { describe, it, expect, vi } from "vitest";
import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { CmsBanner } from "@/lib/cms";
import { isArtwork } from "@/components/home/TileMedia";
import { TrioSection } from "@/components/home/TrioSection";
import { TikTokSection } from "@/components/home/TikTokSection";
import { FeatureSplit } from "@/components/home/FeatureSplit";
import { ShopByCategory } from "@/components/home/ShopByCategory";
import { ConcernsStrip } from "@/components/home/ConcernsStrip";

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

  it("honours artwork on the two small tiles, and gives them a shape to stand in", () => {
    // TileMedia is absolutely positioned, so the copy block is normally these tiles'
    // only height — below `lg` a finished piece would collapse to nothing without the
    // placement's own 2:1 box (2026-09-13).
    const { container } = render(
      <FeatureSplit
        banners={[
          banner({ id: 2, placement: "feature_nature", image_mode: "artwork", title: "Nature" }),
          banner({
            id: 3,
            placement: "feature_collection",
            image_mode: "artwork",
            title: "Naturals",
            cta_url: "/naturals",
          }),
        ]}
      />,
    );
    expect(screen.queryByText("tokè × natural")).toBeNull();
    expect(screen.queryByText("Collection")).toBeNull();
    expect(screen.getByRole("heading", { name: "Nature" })).toHaveClass("sr-only");
    expect(screen.getByRole("heading", { name: "Naturals" })).toHaveClass("sr-only");
    // The linked one is a link named by that heading; the mood tile is not a link.
    expect(screen.getByRole("link", { name: "Naturals" })).toHaveAttribute("href", "/naturals");
    expect(screen.queryByRole("link", { name: "Nature" })).toBeNull();
    // Below `lg` only: measured in Chromium, a ratio still on at `lg` beats the grid's
    // stretch and pushes the whole section from 430px to 634px.
    expect(container.querySelectorAll(".aspect-\\[2\\/1\\].lg\\:aspect-auto")).toHaveLength(2);
  });

  it("leaves the small tiles' copy alone for an ordinary photo", () => {
    render(
      <FeatureSplit
        banners={[
          banner({ id: 2, placement: "feature_nature", title: "Nature" }),
          banner({ id: 3, placement: "feature_collection", title: "Naturals" }),
        ]}
      />,
    );
    expect(screen.getByRole("heading", { name: "Nature" })).not.toHaveClass("sr-only");
    expect(screen.getByText("tokè × natural")).toBeInTheDocument();
  });
});

describe("ShopByCategory", () => {
  const tile = (over: Partial<CmsBanner> = {}) =>
    banner({ placement: "category", title: "Back to School", ...over });

  it("keeps the pill for a photo", () => {
    render(<ShopByCategory banners={[tile()]} />);
    expect(screen.getByText("Back to School")).not.toHaveClass("sr-only");
  });

  it("hides the pill for a finished piece but keeps the link's name", () => {
    // The pill is the ONLY accessible name the tile has — the image renders alt="" —
    // so artwork mode moves it to sr-only rather than dropping it.
    render(<ShopByCategory banners={[tile({ image_mode: "artwork", cta_url: "/bts" })]} />);
    expect(screen.getByText("Back to School")).toHaveClass("sr-only");
    expect(screen.getByRole("link", { name: "Back to School" })).toHaveAttribute("href", "/bts");
  });
});

describe("ConcernsStrip", () => {
  const tile = (over: Partial<CmsBanner> = {}) =>
    banner({ placement: "concern", title: "Acne Care", ...over });

  it("keeps its label and scrim for a photo", () => {
    const { container } = render(<ConcernsStrip banners={[tile()]} />);
    expect(screen.getByText("Acne Care")).not.toHaveClass("sr-only");
    expect(container.querySelectorAll(".bg-black\\/20")).toHaveLength(3);
  });

  it("drops the scrim and the painted label for a finished piece", () => {
    const { container } = render(<ConcernsStrip banners={[tile({ image_mode: "artwork" })]} />);
    expect(screen.getByText("Acne Care")).toHaveClass("sr-only");
    // The two untouched built-in tiles keep theirs.
    expect(container.querySelectorAll(".bg-black\\/20")).toHaveLength(2);
    // It still goes to the tile's built-in destination.
    expect(screen.getByRole("link", { name: "Acne Care" })).toHaveAttribute(
      "href",
      "/products?q=acne",
    );
  });
});
