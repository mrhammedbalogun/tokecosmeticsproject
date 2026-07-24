import { describe, it, expect, beforeEach } from "vitest";
import { pushRecentlyViewed, listRecentlyViewed, RECENT_KEY } from "@/lib/recently-viewed";

const entry = (slug: string) => ({
  slug, name: slug, image: null, from_price: "100.00", currency: "NGN",
});

describe("recently-viewed", () => {
  beforeEach(() => localStorage.clear());

  it("stores newest-first and dedupes by slug", () => {
    pushRecentlyViewed(entry("a"));
    pushRecentlyViewed(entry("b"));
    pushRecentlyViewed(entry("a"));
    expect(listRecentlyViewed().map((e) => e.slug)).toEqual(["a", "b"]);
  });
  it("caps at 8 entries", () => {
    for (let i = 0; i < 12; i++) pushRecentlyViewed(entry(`p${i}`));
    expect(listRecentlyViewed()).toHaveLength(8);
    expect(listRecentlyViewed()[0].slug).toBe("p11");
  });
  it("survives corrupt storage", () => {
    localStorage.setItem(RECENT_KEY, "{not json");
    expect(listRecentlyViewed()).toEqual([]);
  });
});
