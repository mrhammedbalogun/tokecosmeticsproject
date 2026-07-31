import { describe, it, expect } from "vitest";
import { isSlugShaped, slugFollowsName, slugify } from "@/lib/slugify";

describe("slugify", () => {
  it("lowercases and hyphenates a product name", () => {
    expect(slugify("Carrot Shea Butter")).toBe("carrot-shea-butter");
  });

  it("strips accents rather than the letters carrying them", () => {
    // NFKD splits the accent off; dropping the combining mark keeps "cafe", not "caf".
    expect(slugify("Café Crème")).toBe("cafe-creme");
  });

  it("drops punctuation the way Django does", () => {
    expect(slugify("Toke's 100% Natural Soap!")).toBe("tokes-100-natural-soap");
  });

  it("collapses runs of spaces and hyphens into one", () => {
    expect(slugify("Kids   Shampoo -- Gentle")).toBe("kids-shampoo-gentle");
  });

  it("trims hyphens and underscores from the ends", () => {
    expect(slugify("  -Glow Box_  ")).toBe("glow-box");
  });

  it("keeps the underscore, exactly as `\\w` does", () => {
    expect(slugify("men_s essential set")).toBe("men_s-essential-set");
  });

  it("returns empty for a name with nothing sluggable in it", () => {
    // Reachable, and the create action handles it rather than sending "".
    expect(slugify("!!!")).toBe("");
    expect(slugify("   ")).toBe("");
  });

  it("leaves an already-valid slug alone", () => {
    expect(slugify("carrot-shea-butter")).toBe("carrot-shea-butter");
  });
});

describe("isSlugShaped", () => {
  it("accepts what SlugField accepts", () => {
    expect(isSlugShaped("carrot-shea-butter")).toBe(true);
    expect(isSlugShaped("men_s_set_2")).toBe(true);
  });

  it("rejects what would break the URL path it is interpolated into", () => {
    expect(isSlugShaped("carrot shea")).toBe(false);
    expect(isSlugShaped("carrot/shea")).toBe(false);
    expect(isSlugShaped("carrot?x=1")).toBe(false);
    expect(isSlugShaped("")).toBe(false);
  });
});

describe("slugFollowsName", () => {
  it("is true while the slug still matches what the name would produce", () => {
    expect(slugFollowsName("Carrot Shea", "carrot-shea")).toBe(true);
  });

  it("is true for an empty slug, so typing a name fills it", () => {
    expect(slugFollowsName("Carrot Shea", "")).toBe(true);
  });

  it("is FALSE once the slug was chosen by hand", () => {
    // The form stops auto-filling from here. Silently rewriting a deliberate slug is
    // noticed only after the product is live and the URL is wrong.
    expect(slugFollowsName("Carrot Shea", "shea-butter-2026")).toBe(false);
  });
});
