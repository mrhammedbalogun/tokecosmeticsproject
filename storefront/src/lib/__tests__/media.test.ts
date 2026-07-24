import { describe, it, expect, beforeEach } from "vitest";
import { mediaUrl } from "@/lib/media";

describe("mediaUrl", () => {
  beforeEach(() => { process.env.NEXT_PUBLIC_API_URL = "http://localhost:8000"; });

  it("absolutises relative /media paths against the API origin", () => {
    expect(mediaUrl("/media/catalog/products/x.png"))
      .toBe("http://localhost:8000/media/catalog/products/x.png");
  });
  it("passes through absolute URLs", () => {
    expect(mediaUrl("https://cdn.example.com/x.png")).toBe("https://cdn.example.com/x.png");
  });
  it("returns null for null/empty", () => {
    expect(mediaUrl(null)).toBeNull();
    expect(mediaUrl("")).toBeNull();
  });
});
