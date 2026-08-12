import { describe, it, expect } from "vitest";
import {
  addableGateways,
  couponInactiveReason,
  gatewayObstacle,
  marketsWithoutAnAccount,
  nextSortOrder,
  type BankAccountRow,
  type CouponRow,
  type GatewayCatalogEntry,
  type GatewayRow,
} from "@/lib/money-config";

const gateway = (
  country: string,
  gw: string,
  is_active = true,
  over: Partial<GatewayRow> = {},
): GatewayRow => ({
  id: Math.random(), country, country_name: country, country_currency: "NGN",
  gateway: gw, is_active, sort_order: 0, configured: true, missing_settings: [],
  supported_currencies: ["NGN"], ...over,
});

const catalogEntry = (code: string, over: Partial<GatewayCatalogEntry> = {}): GatewayCatalogEntry => ({
  code, supported_currencies: ["NGN"], missing_settings: [], needs: "api_keys", ...over,
});

const account = (country: string, is_active = true): BankAccountRow => ({
  id: Math.random(), country, country_name: country, currency: "NGN",
  bank_name: "GTBank", account_name: "Toke", account_number: "1", extra: {},
  instructions: "", is_active, updated_at: "",
});

const coupon = (over: Partial<CouponRow> = {}): CouponRow => ({
  id: 1, code: "X", type: "percent", value: "10", currency: null, min_subtotal: "0",
  starts_at: null, ends_at: null, usage_limit: null, usage_limit_per_user: null,
  is_active: true, redemption_count: 0, created_at: "", ...over,
});

describe("marketsWithoutAnAccount", () => {
  it("NAMES A MARKET THAT CAN TAKE ORDERS IT CANNOT BE PAID FOR", () => {
    // The backend's own system check warns about exactly this and tells you to fix it in
    // Django admin — which is denied at the vhost.
    const markets = marketsWithoutAnAccount(
      [gateway("NG", "bank_transfer"), gateway("US", "bank_transfer")],
      [account("NG")],
    );

    expect(markets).toEqual(["US"]);
  });

  it("counts an INACTIVE account as no account", () => {
    expect(marketsWithoutAnAccount([gateway("NG", "bank_transfer")], [account("NG", false)])).toEqual(
      ["NG"],
    );
  });

  it("ignores a market whose bank transfer is switched off", () => {
    expect(marketsWithoutAnAccount([gateway("US", "bank_transfer", false)], [])).toEqual([]);
  });

  it("ignores other gateways, which do not need an account", () => {
    expect(marketsWithoutAnAccount([gateway("NG", "paystack")], [])).toEqual([]);
  });
});

describe("couponInactiveReason", () => {
  const now = new Date("2026-08-01T00:00:00Z");

  it("says nothing about a coupon that works", () => {
    expect(couponInactiveReason(coupon(), now)).toBeNull();
  });

  it("explains each way a live-looking coupon does nothing", () => {
    expect(couponInactiveReason(coupon({ is_active: false }), now)).toBe("Switched off");
    expect(couponInactiveReason(coupon({ starts_at: "2026-09-01T00:00:00Z" }), now)).toBe(
      "Starts later",
    );
    expect(couponInactiveReason(coupon({ ends_at: "2026-07-01T00:00:00Z" }), now)).toBe("Expired");
    expect(
      couponInactiveReason(coupon({ usage_limit: 5, redemption_count: 5 }), now),
    ).toBe("Usage limit reached");
  });
});

describe("gatewayObstacle", () => {
  it("is quiet for a row checkout would actually offer", () => {
    expect(gatewayObstacle(gateway("NG", "paystack"))).toBeNull();
  });

  it("names the missing keys — 'on but dark' must be legible, not a mystery", () => {
    const row = gateway("NG", "flutterwave", true, {
      configured: false,
      missing_settings: ["FLUTTERWAVE_SECRET_KEY", "FLUTTERWAVE_SECRET_HASH"],
    });
    expect(gatewayObstacle(row)).toContain("FLUTTERWAVE_SECRET_KEY");
  });

  it("warns when the adapter cannot charge the market's currency", () => {
    // The FW-in-UK future: adding is allowed, but GBP support is what makes it real.
    const row = gateway("GB", "paystack", true, {
      country_currency: "GBP",
      configured: false,
      supported_currencies: ["NGN", "USD"],
    });
    expect(gatewayObstacle(row)).toBe("Cannot charge GBP");
  });

  it("treats an empty currency list as no restriction (bank transfer)", () => {
    const row = gateway("GB", "bank_transfer", true, {
      country_currency: "GBP",
      supported_currencies: [],
    });
    expect(gatewayObstacle(row)).toBeNull();
  });

  it("says a market's bank transfer has no account to pay into", () => {
    const row = gateway("US", "bank_transfer", true, {
      configured: false,
      supported_currencies: [],
    });
    expect(gatewayObstacle(row)).toBe("No active bank account for this market");
  });
});

describe("addableGateways", () => {
  it("offers only what the market does not already have", () => {
    const catalog = [catalogEntry("paystack"), catalogEntry("flutterwave"), catalogEntry("paypal")];
    const rows = [gateway("GB", "paypal"), gateway("GB", "bank_transfer")];
    expect(addableGateways(catalog, rows).map((e) => e.code)).toEqual([
      "paystack",
      "flutterwave",
    ]);
  });
});

describe("nextSortOrder", () => {
  it("lands a new method after everything the market offers", () => {
    expect(
      nextSortOrder([gateway("NG", "a", true, { sort_order: 1 }), gateway("NG", "b", true, { sort_order: 3 })]),
    ).toBe(4);
  });

  it("starts at 1 for an empty market", () => {
    expect(nextSortOrder([])).toBe(1);
  });
});
