import { afterEach, describe, expect, it, vi } from "vitest";

const { apiFetch } = vi.hoisted(() => ({ apiFetch: vi.fn() }));
vi.mock("@/lib/api", () => ({ apiFetch }));

import { getMarketingConfig, NO_TRACKING } from "../marketing";

const CONFIG = {
  tracking_enabled: true,
  consent_version: 2,
  consent_required_countries: ["GB"],
  channels: [{ code: "meta", pixel_id: "PIXEL123", secondary_id: "" }],
};

afterEach(() => { vi.clearAllMocks(); });

describe("getMarketingConfig", () => {
  it("returns the config", async () => {
    apiFetch.mockResolvedValue(CONFIG);
    expect(await getMarketingConfig()).toEqual(CONFIG);
  });

  it("CARRIES THE marketing CACHE TAG, or the kill switch is only advisory", async () => {
    // `tracking_enabled` is a kill switch, `consent_required_countries` is a legal
    // position, and a pixel id decides which ad account receives the shop's customer
    // data. Each is turned off or corrected BECAUSE something is wrong, which is exactly
    // when "within five minutes" is not an answer. The tag is what lets Django's
    // `apps/marketing/revalidate.py` make the save bite immediately; without it there is
    // nothing on the storefront side for a flush to name.
    apiFetch.mockResolvedValue(CONFIG);
    await getMarketingConfig();
    expect(apiFetch).toHaveBeenCalledWith("/marketing/config/", {
      // An HOUR, raised from 300s once the tag existed to carry the urgency. A pixel id
      // changes about once a year; polling for it twelve times an hour bought nothing
      // the flush does not already deliver on save.
      next: { revalidate: 3600, tags: ["marketing"] },
    });
  });

  it("the tag name matches the one Django sends", async () => {
    // Two halves of one contract, in two languages, with nothing but a string between
    // them: apps/marketing/revalidate.py::STOREFRONT_TAG.
    apiFetch.mockResolvedValue(CONFIG);
    await getMarketingConfig();
    const options = apiFetch.mock.calls[0][1] as { next: { tags: string[] } };
    expect(options.next.tags).toContain("marketing");
  });

  it("FAILS CLOSED — an unreachable API loads no pixels at all", async () => {
    // A tracking layer that failed open would start pixels with no consent policy behind
    // them. Losing a day of ad measurement is the cheaper mistake, and it is recoverable.
    apiFetch.mockRejectedValue(new Error("ECONNREFUSED"));
    expect(await getMarketingConfig()).toEqual(NO_TRACKING);
  });
});
