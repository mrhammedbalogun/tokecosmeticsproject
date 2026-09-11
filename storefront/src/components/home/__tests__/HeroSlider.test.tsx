import { describe, it, expect, beforeAll } from "vitest";
import { render, screen } from "@testing-library/react";
import { HeroSlider } from "@/components/home/HeroSlider";
import type { CmsBanner } from "@/lib/cms";

/**
 * The 2026-09-10 crop fix. These lock the two things that went wrong on the live
 * homepage and could not be seen from any unit test at the time: a finished piece of
 * artwork was cropped by `object-cover`, and the site stamped its own headline across
 * the one already painted into the pixels.
 */
const banner = (over: Partial<CmsBanner> = {}): CmsBanner => ({
  id: 1,
  title: "Toke Back To School",
  subtitle: "",
  image: "https://cdn/catalog/library/art.png",
  mobile_image: null,
  cta_text: "",
  cta_url: "",
  video_url: "",
  video_mode: "loop",
  image_mode: "overlay",
  tagline: "",
  placement: "hero",
  sort: 0,
  ...over,
});

beforeAll(() => {
  // useSyncExternalStore reads this on the client; jsdom has no matchMedia.
  window.matchMedia = ((q: string) => ({
    matches: true,
    media: q,
    addEventListener: () => {},
    removeEventListener: () => {},
  })) as unknown as typeof window.matchMedia;
});

describe("HeroSlider — artwork vs overlay", () => {
  it("crops an overlay photo to fill and writes the site's own copy over it", () => {
    const { container } = render(
      <HeroSlider
        banners={[banner({ subtitle: "Premium", title: "Healthy Skin", cta_text: "Shop", cta_url: "/products" })]}
      />,
    );
    expect(container.querySelector("img")).toHaveClass("object-cover");
    // The headline is VISIBLE copy, not a screen-reader-only label.
    expect(screen.getByRole("heading", { level: 1 })).not.toHaveClass("sr-only");
    expect(screen.getByText("Premium")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Shop" })).toHaveAttribute("href", "/products");
  });

  it("shows a finished artwork whole, and adds no text of its own", () => {
    const { container } = render(<HeroSlider banners={[banner({ image_mode: "artwork" })]} />);
    // object-contain never crops, whatever shape the box is.
    const imgs = [...container.querySelectorAll("img")];
    expect(imgs.some((i) => i.className.includes("object-contain"))).toBe(true);
    // …with a blurred copy of itself behind, so any letterbox band is not bare white.
    expect(imgs.some((i) => i.className.includes("blur"))).toBe(true);
    // The artwork already carries its headline; ours stays for structure only.
    expect(screen.getByRole("heading", { level: 1 })).toHaveClass("sr-only");
    // …and the darkening scrims that exist to make OUR text legible are gone.
    expect(container.querySelector(".bg-gradient-to-r")).toBeNull();
  });

  it("makes the whole artwork the link, because its button is painted on", () => {
    render(<HeroSlider banners={[banner({ image_mode: "artwork", cta_url: "/promo" })]} />);
    const link = screen.getByRole("link", { name: "Toke Back To School" });
    expect(link).toHaveAttribute("href", "/promo");
  });

  it("treats a banner from a backend that predates the field as an overlay photo", () => {
    const old = banner();
    // What the wire looked like before 2026-09-10.
    delete (old as Partial<CmsBanner>).image_mode;
    const { container } = render(<HeroSlider banners={[old]} />);
    expect(container.querySelector("img")).toHaveClass("object-cover");
    expect(screen.getByRole("heading", { level: 1 })).not.toHaveClass("sr-only");
  });

  it("keeps a hidden slide's copy inert, so it cannot swallow the arrows' clicks", () => {
    // Every slide is stacked on every other one. The four nobody is looking at are held
    // off by `pointer-events-none`; anything inside them that re-enables events puts an
    // invisible headline over the Next button.
    const { container } = render(
      <HeroSlider banners={[banner({ id: 1, title: "One" }), banner({ id: 2, title: "Two" })]} />,
    );
    const hidden = [...container.querySelectorAll("section > div")].filter((d) =>
      d.className.includes("opacity-0"),
    );
    expect(hidden.length).toBe(1);
    expect(hidden[0].querySelector(".pointer-events-auto")).toBeNull();
  });

  it("falls back to speaking for itself when artwork mode has no artwork", () => {
    // "Show the picture, add no words" with no picture is a blank gradient nobody can read.
    render(<HeroSlider banners={[banner({ image_mode: "artwork", image: null })]} />);
    expect(screen.getByRole("heading", { level: 1 })).not.toHaveClass("sr-only");
  });

  it("sizes the box by the artwork's ratio, never by a slice of the window", () => {
    const { container } = render(<HeroSlider banners={[banner()]} />);
    const section = container.querySelector("section")!;
    expect(section.className).toContain("aspect-[16/9]");
    // A vh height is what cropped every banner differently on every screen.
    expect(section.className).not.toContain("vh]");
  });
});
