import { describe, it, expect } from "vitest";
import { apiLabel, isProductionApi } from "@/lib/env";

describe("the STAGING badge fails loud", () => {
  it("treats the real production API as production", () => {
    expect(isProductionApi("https://api.tokecosmetics.com")).toBe(true);
    expect(isProductionApi("https://api.tokecosmetics.com/")).toBe(true);
  });

  it("treats anything else — including an unset value — as NOT production", () => {
    // Being told "staging" while on production costs a moment's confusion. The reverse
    // costs a production refund made in the belief it was a rehearsal.
    expect(isProductionApi(undefined)).toBe(false);
    expect(isProductionApi("")).toBe(false);
    expect(isProductionApi("http://localhost:8000")).toBe(false);
    expect(isProductionApi("https://staging-api.tokecosmetics.com")).toBe(false);
    // A lookalike host must not pass.
    expect(isProductionApi("https://api.tokecosmetics.com.evil.example")).toBe(false);
  });

  it("labels the badge with the API host so it says WHICH environment", () => {
    expect(apiLabel("http://localhost:8000")).toBe("localhost:8000");
    expect(apiLabel(undefined)).toBe("API unset");
    expect(apiLabel("not a url")).toBe("not a url");
  });
});
