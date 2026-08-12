import { describe, it, expect } from "vitest";
import { welcomeFor } from "@/lib/geo";

const MARKETS = ["NG", "GB", "US", "CA", "ZZ"];

describe("welcomeFor", () => {
  it("confirms when geo matches the market the visitor is already on (geo-seeded cookie)", () => {
    expect(welcomeFor("CA", "CA", MARKETS)).toEqual({ kind: "confirm", market: "CA" });
  });

  it("confirms ZZ for an unknown geo country whose cookie was seeded ZZ", () => {
    // A French visitor: the proxy seeded ZZ, and FR resolves to ZZ — same market, confirm.
    expect(welcomeFor("ZZ", "FR", MARKETS)).toEqual({ kind: "confirm", market: "ZZ" });
  });

  it("offers a switch when the cookie disagrees with geo (pre-geo-seeding visitors)", () => {
    expect(welcomeFor("NG", "CA", MARKETS)).toEqual({ kind: "offer", market: "CA" });
  });

  it("offers ZZ when an unknown geo country disagrees with the cookie", () => {
    expect(welcomeFor("NG", "FR", MARKETS)).toEqual({ kind: "offer", market: "ZZ" });
  });

  it("says nothing when geo resolves to the NG home default", () => {
    expect(welcomeFor("NG", "NG", MARKETS)).toBeNull();
  });

  it("says nothing when geo is absent", () => {
    expect(welcomeFor("NG", undefined, MARKETS)).toBeNull();
    expect(welcomeFor("NG", "", MARKETS)).toBeNull();
  });

  it("uppercases a lowercase geo code before matching", () => {
    expect(welcomeFor("GB", "gb", MARKETS)).toEqual({ kind: "confirm", market: "GB" });
  });
});
