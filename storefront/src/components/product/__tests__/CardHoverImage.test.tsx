import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToString } from "react-dom/server";
import { ProductCard } from "@/components/product/ProductCard";
import type { ProductCard as ProductCardData } from "@/lib/catalog";

/**
 * The hover artwork is gated on `(hover: hover)`, not on a breakpoint.
 *
 * What these tests can and cannot prove: jsdom never fetches images, so "no network
 * request" is not directly observable here. What IS observable — and what actually
 * decides whether a request happens — is whether an `<img>` with a resolvable `src`
 * exists in the document at all. An element that is absent cannot be fetched by any
 * browser, under any heuristic; that is the whole point of choosing absence over
 * `opacity-0` (which loads) or `display:none` (which usually does not, but is not
 * promised to). So these assert presence/absence of the element and its src.
 */

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

const listeners = new Set<() => void>();
let hoverCapable = true;

function installMatchMedia() {
  vi.stubGlobal("matchMedia", (q: string) => ({
    matches: q.includes("hover: hover") ? hoverCapable : false,
    media: q,
    addEventListener: (_: string, cb: () => void) => listeners.add(cb),
    removeEventListener: (_: string, cb: () => void) => listeners.delete(cb),
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  }));
}

beforeEach(() => { hoverCapable = true; listeners.clear(); installMatchMedia(); });
afterEach(() => vi.unstubAllGlobals());

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
    rating_avg: "4.50",
    rating_count: 12,
    ...overrides,
  } as ProductCardData;
}

function renderCard(data: ProductCardData) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ProductCard product={data} />
    </QueryClientProvider>,
  );
}

/** The hover artwork is the decorative one — alt="" and aria-hidden. */
const hoverImg = (c: HTMLElement) =>
  Array.from(c.querySelectorAll("img")).filter((i) => i.getAttribute("alt") === "");

const WITH_HOVER = { hover_image: "/media/catalog/products/serum-alt.png" };

describe("a device that can hover (desktop)", () => {
  it("renders the hover artwork, so the swap still works", () => {
    const { container } = renderCard(make(WITH_HOVER));
    expect(hoverImg(container)).toHaveLength(1);
  });

  it("keeps the exact hover classes and decorative semantics", () => {
    const { container } = renderCard(make(WITH_HOVER));
    const [el] = hoverImg(container);

    expect(el).toHaveAttribute("aria-hidden", "true");
    expect(el.className).toContain("opacity-0");
    expect(el.className).toContain("group-hover:opacity-100");
    expect(el.className).toContain("group-hover:scale-[1.04]");
    expect(el.className).toContain("duration-500");
  });

  it("requests it at the same widths as the primary, so the swap cannot jump", () => {
    const { container } = renderCard(make(WITH_HOVER));
    const [el] = hoverImg(container);
    const primary = screen.getByAltText("Radiance Glow Serum");

    expect(el.getAttribute("sizes")).toBe(primary.getAttribute("sizes"));
  });
});

describe("a device that cannot hover (phone/tablet)", () => {
  beforeEach(() => { hoverCapable = false; });

  it("renders NO hover <img> at all — nothing exists for the browser to fetch", () => {
    const { container } = renderCard(make(WITH_HOVER));
    expect(hoverImg(container)).toHaveLength(0);
  });

  it("emits no URL pointing at the hover artwork anywhere in the markup", () => {
    const { container } = renderCard(make(WITH_HOVER));
    // Belt and braces: not merely hidden, not in a srcset, not in a preload — absent.
    expect(container.innerHTML).not.toContain("serum-alt");
  });

  it("still shows the primary artwork, unchanged", () => {
    renderCard(make(WITH_HOVER));
    const primary = screen.getByAltText("Radiance Glow Serum");
    expect(primary).toBeInTheDocument();
    expect(primary.getAttribute("src")).toContain("serum.png");
  });

  it("keeps the card's box identical, so nothing shifts", () => {
    hoverCapable = true;
    const withHover = renderCard(make(WITH_HOVER)).container.querySelector(".aspect-\\[3\\/4\\]");
    const hoverBox = withHover?.className;
    hoverCapable = false;
    const withoutHover = renderCard(make(WITH_HOVER)).container.querySelector(".aspect-\\[3\\/4\\]");

    expect(withoutHover?.className).toBe(hoverBox);
  });
});

describe("a product with no hover artwork behaves exactly as before", () => {
  it("renders one image on a hover-capable device", () => {
    const { container } = renderCard(make());
    expect(hoverImg(container)).toHaveLength(0);
    expect(screen.getByAltText("Radiance Glow Serum")).toBeInTheDocument();
  });

  it("renders one image on a touch device", () => {
    hoverCapable = false;
    const { container } = renderCard(make());
    expect(hoverImg(container)).toHaveLength(0);
    expect(screen.getByAltText("Radiance Glow Serum")).toBeInTheDocument();
  });

  it("leaves the primary WITHOUT the fade-out, since there is nothing to fade to", () => {
    renderCard(make());
    expect(screen.getByAltText("Radiance Glow Serum").className)
      .not.toContain("group-hover:opacity-0");
  });
});

describe("hydration safety", () => {
  it("the server snapshot renders nothing, so the hydration tree matches the server", () => {
    // useSyncExternalStore's third argument is the server snapshot. Rendering through
    // renderToString exercises exactly that path — if it emitted the image while the
    // client's first pass did not, React would warn on hydrate.
    hoverCapable = true;
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const html = renderToString(
      <QueryClientProvider client={qc}>
        <ProductCard product={make(WITH_HOVER)} />
      </QueryClientProvider>,
    );
    expect(html).not.toContain("serum-alt");
    expect(html).toContain("serum.png");
  });
});
