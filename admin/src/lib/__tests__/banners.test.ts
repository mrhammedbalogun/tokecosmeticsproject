import { describe, it, expect } from "vitest";
import { bannerState, livePlacement, type BannerRow } from "@/lib/banners";

const banner = (over: Partial<BannerRow> = {}): BannerRow => ({
  id: 1, title: "Sale", subtitle: "", image: null, mobile_image: null, video: null,
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
