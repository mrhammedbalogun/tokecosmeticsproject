import { describe, expect, it } from "vitest";
import {
  applicationsQueryString,
  formatBytes,
  jobsQueryString,
  parseApplicationFilters,
  parseJobFilters,
  whatsappUrl,
} from "@/lib/careers";

describe("job filters", () => {
  it("round-trips a status and a search term, omitting page 1", () => {
    const filters = parseJobFilters(new URLSearchParams("status=draft&q=sales"));
    expect(filters).toEqual({ status: "draft", q: "sales", page: 1 });
    expect(jobsQueryString(filters)).toBe("status=draft&q=sales");
  });

  it("clamps a junk page number to 1 rather than sending NaN", () => {
    expect(parseJobFilters(new URLSearchParams("page=not-a-number")).page).toBe(1);
    expect(parseJobFilters(new URLSearchParams("page=-4")).page).toBe(1);
  });

  it("trims the search term, so a stray space is not a different query", () => {
    expect(parseJobFilters(new URLSearchParams("q=%20sales%20")).q).toBe("sales");
  });
});

describe("application filters", () => {
  it("carries the role filter through, which is how the roles table links here", () => {
    const filters = parseApplicationFilters(new URLSearchParams("job=7&status=new"));
    expect(applicationsQueryString(filters)).toBe("job=7&status=new");
  });

  it("keeps page 2 but never writes page 1", () => {
    const filters = parseApplicationFilters(new URLSearchParams("page=2"));
    expect(applicationsQueryString(filters)).toBe("page=2");
    expect(applicationsQueryString({ ...filters, page: 1 })).toBe("");
  });
});

describe("whatsappUrl", () => {
  it("strips the E.164 punctuation wa.me will not take", () => {
    // Built from the STORED diallable value, never from the prettified display form —
    // the same rule the store cards follow.
    expect(whatsappUrl("+2348023900964")).toBe("https://wa.me/2348023900964");
  });
});

describe("formatBytes", () => {
  it("tells a one-page PDF from a scanned booklet before it is opened", () => {
    expect(formatBytes(480 * 1024)).toBe("480 KB");
    expect(formatBytes(2.1 * 1024 * 1024)).toBe("2.1 MB");
  });

  it("renders nothing rather than '0 KB' when the size is unknown", () => {
    expect(formatBytes(0)).toBe("");
  });
});
