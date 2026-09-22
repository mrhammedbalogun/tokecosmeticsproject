import { describe, expect, it, vi, beforeEach } from "vitest";
import { render } from "@testing-library/react";
import { PurchaseTracker } from "@/components/checkout/PurchaseTracker";
import { LateGoogleAdsConversion } from "@/components/orders/LateGoogleAdsConversion";
import type { MarketingConfig } from "@/lib/marketing";
import type { OrderItem } from "@/lib/orders";

const CONFIG: MarketingConfig = {
  tracking_enabled: true, consent_version: 1, consent_required_countries: [],
  channels: [{ code: "google_ads", pixel_id: "AW-123", secondary_id: "AbC-D_efG" }],
} as MarketingConfig;

const ITEMS: OrderItem[] = [{
  product_name: "Radiance Serum", variant_name: "150ml", sku: "SKU-1", quantity: 1,
  unit_price: "5000", line_total: "5000", unit_price_display: "₦5,000",
  line_total_display: "₦5,000", image_url: null,
}];

function tracker(status: string, number = "TC-100147") {
  return render(
    <PurchaseTracker
      orderNumber={number} status={status} currency="NGN" value={5000}
      items={ITEMS} config={CONFIG}
    />,
  );
}

const gtag = () => window.gtag as unknown as ReturnType<typeof vi.fn>;
/** Only the Google Ads conversion — `track()` also sends GA4 a "purchase" event. */
const conversions = () => gtag().mock.calls.filter((c) => c[1] === "conversion");

beforeEach(() => {
  localStorage.clear();
  window.gtag = vi.fn();
  window.fbq = vi.fn();
});

describe("nothing is reported before the money lands", () => {
  /** The bug this closes: `ReviewStep` pushes a bank-transfer customer to the
   * confirmation page the moment the order is PLACED, and the pixel fired there and
   * then. See lib/tracking/paid.ts for how often that really happened. */
  it("fires nothing for an order still awaiting a transfer", () => {
    tracker("pending_payment");
    expect(window.fbq).not.toHaveBeenCalled();
    expect(gtag()).not.toHaveBeenCalled();
  });

  it("fires nothing for an order that expired unpaid", () => {
    tracker("expired");
    expect(window.fbq).not.toHaveBeenCalled();
  });

  it("fires for an order that reached processing", () => {
    tracker("processing");
    expect(window.fbq).toHaveBeenCalled();
    expect(gtag()).toHaveBeenCalledWith("event", "conversion", expect.objectContaining({
      send_to: "AW-123/AbC-D_efG", transaction_id: "TC-100147",
    }));
  });

  /** The whole point of the gate being a gate and not a refusal: the customer who pays
   * their transfer and comes back must still be counted. */
  it("fires on a later visit once the same order has been paid", () => {
    tracker("pending_payment", "TC-1");
    expect(window.fbq).not.toHaveBeenCalled();
    tracker("processing", "TC-1");
    expect(window.fbq).toHaveBeenCalledTimes(1);
  });
});

describe("once per order, across sessions", () => {
  it("does not report the same order twice on a remount", () => {
    tracker("processing");
    tracker("processing");
    expect(window.fbq).toHaveBeenCalledTimes(1);
    // `track()` sends GA4 its own "purchase" event, so counting bare "event" calls
    // counts two things. The Ads conversion is the one that must be unique.
    expect(conversions()).toHaveLength(1);
  });

  it("lets the late Google-only surface report an order the confirmation page never could", () => {
    render(
      <LateGoogleAdsConversion
        orderNumber="TC-2" status="processing" currency="NGN" value={5000} config={CONFIG}
      />,
    );
    expect(gtag()).toHaveBeenCalledWith("event", "conversion", expect.objectContaining({
      transaction_id: "TC-2",
    }));
    // The four-platform key is untouched, so Meta et al. are NOT fired from here.
    expect(window.fbq).not.toHaveBeenCalled();
  });

  it("does not let the two surfaces both report one order", () => {
    tracker("processing", "TC-3");
    const after = conversions().length;
    render(
      <LateGoogleAdsConversion
        orderNumber="TC-3" status="processing" currency="NGN" value={5000} config={CONFIG}
      />,
    );
    expect(conversions()).toHaveLength(after);
  });
});
