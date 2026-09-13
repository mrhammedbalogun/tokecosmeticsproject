import { describe, it, expect } from "vitest";
import { bannerState, livePlacement, type BannerRow } from "@/lib/banners";

const banner = (over: Partial<BannerRow> = {}): BannerRow => ({
  id: 1, title: "Sale", subtitle: "", image: null, mobile_image: null, video: null,
  video_mode: "loop", image_mode: "overlay", tagline: "",
  cta_text: "", cta_url: "", placement: "strip", sort: 0,
  starts_at: null, ends_at: null, is_active: true, countries: [], updated_at: "",
  ...over,
});

const now = new Date("2026-08-01T12:00:00Z");

describe("bannerState", () => {
  it("distinguishes the four things a ticked checkbox can mean", () => {
    expect(bannerState(banner(), now)).toBe("live");
    expect(bannerState(banner({ is_active: false }), now)).toBe("off");
    expect(bannerState(banner({ starts_at: "2026-09-01T00:00:00Z" }), now)).toBe("scheduled");
    expect(bannerState(banner({ ends_at: "2026-07-01T00:00:00Z" }), now)).toBe("ended");
  });

  it("counts a banner inside its window as live", () => {
    const inWindow = banner({ starts_at: "2026-07-01T00:00:00Z", ends_at: "2026-09-01T00:00:00Z" });
    expect(bannerState(inWindow, now)).toBe("live");
  });
});

describe("livePlacement", () => {
  it("returns only live banners of that placement, in sort order", () => {
    const rows = [
      banner({ id: 1, placement: "strip", sort: 2, title: "second" }),
      banner({ id: 2, placement: "strip", sort: 1, title: "first" }),
      banner({ id: 3, placement: "hero", sort: 0, title: "hero" }),
      banner({ id: 4, placement: "strip", sort: 0, is_active: false, title: "off" }),
    ];

    expect(livePlacement(rows, "strip", now).map((b) => b.title)).toEqual(["first", "second"]);
  });
});

describe("specRatio — the shape a placement asks for", () => {
  it("reads both forms the placement catalogue uses", async () => {
    const { specRatio } = await import("@/lib/image");
    expect(specRatio("aspect-video")).toBeCloseTo(16 / 9);
    expect(specRatio("aspect-[3/4]")).toBeCloseTo(0.75);
    expect(specRatio("aspect-[16/7]")).toBeCloseTo(16 / 7);
    // The news marquee has no artwork, so it has no shape to check against.
    expect(specRatio("")).toBeNull();
    expect(specRatio("aspect-nonsense")).toBeNull();
  });
});

describe("the placement catalogue", () => {
  /**
   * Every media placement on /home-content offers "A photo / Finished artwork"
   * (2026-09-13). This is the guard on the next placement someone adds: a section the
   * marketer can upload a picture to but cannot tell the shop to stop writing over is
   * the gap this feature closed, and it is invisible until they try it.
   *
   * The two affiliate slots are the deliberate exception — they are edited at
   * /content/affiliates, have no copy to suppress, and their boxes are not pinned.
   */
  it("offers a photo/artwork choice on every Home Content image section", async () => {
    const { PLACEMENTS } = await import("@/lib/banners");
    const homeContent = PLACEMENTS.filter((p) => !p.value.startsWith("affiliate_"));
    const withoutChoice = homeContent.filter((p) => p.media && !p.imageMode);
    expect(withoutChoice.map((p) => p.value)).toEqual([]);
    // The news marquee is text; it must not sprout an image control.
    expect(homeContent.find((p) => p.value === "strip")?.imageMode).toBeUndefined();
  });

  it("says what artwork MEANS wherever it offers it — the promises differ", async () => {
    const { PLACEMENTS } = await import("@/lib/banners");
    for (const p of PLACEMENTS.filter((s) => s.imageMode)) {
      expect(p.artworkMeans, p.value).toBeDefined();
      // "Shown whole" is a promise only a box pinned to the artwork's own ratio can
      // keep. Every other placement's shape is fixed by the homepage grid.
      if (p.artworkMeans === "whole") expect(p.value).toBe("hero");
    }
  });
});
