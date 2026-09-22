import { describe, expect, it, vi, beforeEach } from "vitest";
import { trackGoogleAdsConversion } from "@/lib/tracking/events";
import { googleUserDataFromOrder } from "@/lib/tracking/user-data";
import { isPaidStatus } from "@/lib/tracking/paid";
import type { OrderDetail } from "@/lib/orders";

function order(overrides: Partial<OrderDetail> = {}): OrderDetail {
  return {
    number: "TC-100147", status: "processing", placed_at: "", currency: "NGN",
    country: "NG", email: "Amina.Bello@Gmail.com ", phone: "+2348012345678",
    subtotal: "5000", discount_total: "0", shipping_total: "0", tax_total: "0",
    tax_label: "VAT", grand_total: "5000", grand_total_display: "₦5,000",
    delivery_option_name: null, billing_address: null, customer_note: "",
    payment_gateway: "bank_transfer", items: [], tracking_carrier: "", tracking_number: "",
    shipping_address: {
      first_name: "Amina", last_name: "Bello", line1: "12 Awolowo Road",
      city_text: "Ikoyi", state_text: "Lagos", country_code: "NG",
    },
    ...overrides,
  } as OrderDetail;
}

const gtagCalls = () => (window.gtag as unknown as ReturnType<typeof vi.fn>).mock.calls;

beforeEach(() => {
  window.gtag = vi.fn();
});

describe("the paid gate", () => {
  it("refuses every status where the money is not in", () => {
    for (const s of ["pending_payment", "expired", "cancelled", "refunded"]) {
      expect(isPaidStatus(s)).toBe(false);
    }
  });

  it("accepts the statuses at or past the paid transition", () => {
    for (const s of ["processing", "on_hold", "shipped", "delivered", "completed"]) {
      expect(isPaidStatus(s)).toBe(true);
    }
  });

  /** An allowlist, so a status the backend adds tomorrow reports nothing until someone
   * decides it should. */
  it("refuses a status it has never heard of", () => {
    expect(isPaidStatus("awaiting_review")).toBe(false);
  });
});

describe("user data sent to Google", () => {
  it("sets user_data BEFORE the conversion event, or the tag builds the hit without it", () => {
    trackGoogleAdsConversion("AW-123", "AbC-D_efG", {
      value: 5000, currency: "NGN", orderNumber: "TC-100147",
      userData: googleUserDataFromOrder(order()),
    });
    const calls = gtagCalls();
    expect(calls[0][0]).toBe("set");
    expect(calls[0][1]).toBe("user_data");
    expect(calls[1][0]).toBe("event");
  });

  it("passes the email through unhashed and untouched apart from case — Google owns the gmail dot rule", () => {
    trackGoogleAdsConversion("AW-123", "L", {
      value: 1, currency: "NGN", userData: googleUserDataFromOrder(order()),
    });
    // NOT "aminabello@gmail.com": stripping the dots here is the server's job
    // (channels/google_ads._google_email), and doing it twice matches nobody.
    expect(gtagCalls()[0][2]).toMatchObject({ email: "amina.bello@gmail.com" });
  });

  it("drops a phone that is not E.164 rather than sending a wasted identifier", () => {
    trackGoogleAdsConversion("AW-123", "L", {
      value: 1, currency: "NGN",
      userData: googleUserDataFromOrder(order({ phone: "08012345678" })),
    });
    expect(gtagCalls()[0][2]).not.toHaveProperty("phone_number");
  });

  /** The Nigerian case, and the reason the server adapter omits the address too: a
   * partial address is not a partial match. */
  it("omits the address entirely when there is no postcode", () => {
    trackGoogleAdsConversion("AW-123", "L", {
      value: 1, currency: "NGN", userData: googleUserDataFromOrder(order()),
    });
    expect(gtagCalls()[0][2]).not.toHaveProperty("address");
  });

  it("includes the address once all four identifying parts are present", () => {
    const withPostcode = order({
      shipping_address: {
        first_name: "Amina", last_name: "Bello", line1: "12 Awolowo Road",
        city_text: "Ikoyi", state_text: "Lagos", country_code: "NG", postcode: "101233",
      },
    });
    trackGoogleAdsConversion("AW-123", "L", {
      value: 1, currency: "NGN", userData: googleUserDataFromOrder(withPostcode),
    });
    expect(gtagCalls()[0][2]).toMatchObject({
      address: {
        first_name: "Amina", last_name: "Bello", postal_code: "101233",
        country: "NG", street: "12 Awolowo Road", city: "Ikoyi", region: "Lagos",
      },
    });
  });

  it("fires the conversion with no user_data at all rather than not firing", () => {
    trackGoogleAdsConversion("AW-123", "L", { value: 1, currency: "NGN" });
    const calls = gtagCalls();
    expect(calls).toHaveLength(1);
    expect(calls[0][0]).toBe("event");
  });
});
