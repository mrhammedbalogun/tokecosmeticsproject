import { describe, it, expect } from "vitest";
import {
  couponInactiveReason,
  marketsWithoutAnAccount,
  type BankAccountRow,
  type CouponRow,
  type GatewayRow,
} from "@/lib/money-config";

const gateway = (country: string, gw: string, is_active = true): GatewayRow => ({
  id: Math.random(), country, gateway: gw, is_active, sort_order: 0,
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
