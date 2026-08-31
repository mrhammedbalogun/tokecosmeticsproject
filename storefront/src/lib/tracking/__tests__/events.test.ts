/**
 * The browser half of each vendor's vocabulary, and the guards that stop a pixel
 * breaking the shop.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { type TrackedEvent, track, trackGoogleAdsConversion } from "@/lib/tracking/events";

const ITEM = { sku: "SKU-1", name: "Radiance Serum", price: 2500, quantity: 2 };

/** Annotated as `TrackedEvent` rather than `as const`: the const assertion made `items`
 * readonly, which does not satisfy the mutable `TrackedItem[]` the real signature takes.
 * vitest does not typecheck, so it passed at runtime and only `tsc` ever saw it. */
function baseEvent(name: "purchase" | "add_to_cart" = "purchase"): TrackedEvent {
  return {
    name,
    eventId: "TC-100147",
    currency: "NGN",
    value: 5000,
    items: [ITEM],
    ...(name === "purchase" ? { orderNumber: "TC-100147" } : {}),
  };
}

beforeEach(() => {
  delete window.fbq;
  delete window.ttq;
  delete window.snaptr;
  delete window.gtag;
});

describe("deduplication", () => {
  it("hands every platform the SAME event id, in the key each of them reads", () => {
    // This is the whole reason a purchase is not counted twice. Meta reads `eventID` in
    // its options argument, TikTok `event_id`, Snapchat `client_dedup_id`.
    window.fbq = vi.fn();
    window.ttq = { track: vi.fn() };
    window.snaptr = vi.fn();

    track(baseEvent());

    expect(window.fbq).toHaveBeenCalledWith(
      "track", "Purchase", expect.anything(), { eventID: "TC-100147" },
    );
    expect(window.ttq.track).toHaveBeenCalledWith(
      "CompletePayment", expect.anything(), { event_id: "TC-100147" },
    );
    expect(window.snaptr).toHaveBeenCalledWith(
      "track", "PURCHASE", expect.objectContaining({ client_dedup_id: "TC-100147" }),
    );
  });
});

describe("each vendor's own spelling", () => {
  it("uses CompletePayment for TikTok and ADD_CART for Snapchat", () => {
    window.ttq = { track: vi.fn() };
    window.snaptr = vi.fn();

    track({ ...baseEvent("add_to_cart") });

    expect(window.ttq.track).toHaveBeenCalledWith("AddToCart", expect.anything(), expect.anything());
    // Not ADD_TO_CART. Snap's own name, and a silent no-match if it is wrong.
    expect(window.snaptr).toHaveBeenCalledWith("track", "ADD_CART", expect.anything());
  });

  it("sends Snapchat its price as a string, as its API also demands", () => {
    window.snaptr = vi.fn();
    track(baseEvent());
    expect(window.snaptr).toHaveBeenCalledWith(
      "track", "PURCHASE", expect.objectContaining({ price: "5000" }),
    );
  });

  it("sends Meta a number and the SKUs as content_ids", () => {
    window.fbq = vi.fn();
    track(baseEvent());
    expect(window.fbq).toHaveBeenCalledWith("track", "Purchase", expect.objectContaining({
      value: 5000, currency: "NGN", content_ids: ["SKU-1"], content_type: "product",
    }), expect.anything());
  });

  it("translates to GA4's vocabulary", () => {
    window.gtag = vi.fn();
    track(baseEvent());
    expect(window.gtag).toHaveBeenCalledWith("event", "purchase", expect.objectContaining({
      transaction_id: "TC-100147",
      items: [expect.objectContaining({ item_id: "SKU-1" })],
    }));
  });
});

describe("the guards", () => {
  it("does nothing at all when no pixel is loaded", () => {
    // Which is the NORMAL case for a visitor who refused: the scripts were never
    // injected, so the globals do not exist. It must not throw into a click handler.
    expect(() => track(baseEvent())).not.toThrow();
  });

  it("survives a pixel that throws", () => {
    window.fbq = vi.fn(() => { throw new Error("blocked by extension"); });
    window.ttq = { track: vi.fn() };

    expect(() => track(baseEvent())).not.toThrow();
    // And the others still fire — one broken vendor must not silence the rest.
    expect(window.ttq.track).toHaveBeenCalled();
  });
});

describe("the Google Ads conversion", () => {
  it("names the conversion id AND the label, or the ad account sees nothing", () => {
    window.gtag = vi.fn();
    trackGoogleAdsConversion("AW-123", "AbC-D_efG", {
      value: 5000, currency: "NGN", orderNumber: "TC-100147",
    });
    expect(window.gtag).toHaveBeenCalledWith("event", "conversion", expect.objectContaining({
      send_to: "AW-123/AbC-D_efG",
    }));
  });

  it("refuses to fire without a label rather than sending a conversion nothing counts", () => {
    window.gtag = vi.fn();
    trackGoogleAdsConversion("AW-123", "", { value: 1, currency: "NGN" });
    expect(window.gtag).not.toHaveBeenCalled();
  });
});
