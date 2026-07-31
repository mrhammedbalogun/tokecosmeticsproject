import { describe, it, expect } from "vitest";
import { addressLines, mayTransition, totalRows, type OrderDetail } from "@/lib/order-detail";

const order = (over: Partial<OrderDetail> = {}): OrderDetail => ({
  number: "TC-100001",
  status: "processing",
  review_reason: "",
  placed_at: "2026-07-30T10:00:00Z",
  email: "buyer@example.test",
  phone: "+2348012345678",
  user_email: "",
  country: "NG",
  currency: "NGN",
  subtotal: "2000.00",
  discount_total: "0.00",
  shipping_total: "0.00",
  tax_total: "0.00",
  grand_total: "2000.00",
  grand_total_display: "₦2,000.00",
  delivery_option_name: "",
  shipping_address: {},
  billing_address: {},
  customer_note: "",
  admin_note: "",
  tracking_carrier: "",
  tracking_number: "",
  source: "web",
  legacy_number: "",
  items: [],
  events: [],
  payments: [],
  allowed_transitions: [],
  ...over,
});

describe("mayTransition", () => {
  it("allows a move that needs no scope", () => {
    expect(mayTransition({ status: "shipped", requires_scope: null }, [])).toBe(true);
  });

  it("allows an elevated move to somebody holding the scope", () => {
    expect(
      mayTransition({ status: "cancelled", requires_scope: "orders.manage" }, ["orders.manage"]),
    ).toBe(true);
  });

  it("refuses an elevated move to somebody without it", () => {
    // Support holds orders.operate. Rendering Cancel as clickable would produce a 403 the
    // operator cannot explain.
    expect(
      mayTransition({ status: "cancelled", requires_scope: "orders.manage" }, ["orders.operate"]),
    ).toBe(false);
  });
});

describe("addressLines", () => {
  it("orders the known fields the way a label is written", () => {
    const lines = addressLines({
      country: "NG",
      line1: "12 Adeola Odeku",
      first_name: "Jane",
      state: "Lagos",
      last_name: "Doe",
      area: "Victoria Island",
    });

    expect(lines).toEqual([
      "Jane",
      "Doe",
      "12 Adeola Odeku",
      "Victoria Island",
      "Lagos",
      "NG",
    ]);
  });

  it("KEEPS A KEY IT DOES NOT KNOW rather than dropping it", () => {
    // shipping_address is a JSON blob captured at checkout and its keys vary by country.
    // An address with an unanticipated key should still be postable.
    const lines = addressLines({ line1: "12 Adeola Odeku", landmark: "opposite the school" });

    expect(lines).toContain("opposite the school");
  });

  it("skips empty values rather than rendering blank lines", () => {
    expect(addressLines({ line1: "12 Adeola Odeku", line2: "", state: "Lagos" })).toEqual([
      "12 Adeola Odeku",
      "Lagos",
    ]);
  });

  it("copes with a legacy order that has no address at all", () => {
    expect(addressLines({})).toEqual([]);
    expect(addressLines(null)).toEqual([]);
  });
});

describe("totalRows", () => {
  it("hides the zero rows that only add noise", () => {
    const rows = totalRows(order());

    expect(rows.map((r) => r.label)).toEqual(["Subtotal", "Total"]);
  });

  it("shows a discount as a negative", () => {
    const rows = totalRows(order({ discount_total: "500.00" }));

    expect(rows.find((r) => r.label === "Discount")?.value).toBe("−500.00");
  });

  it("shows delivery and tax when they are not zero", () => {
    const rows = totalRows(order({ shipping_total: "1500.00", tax_total: "150.00" }));

    expect(rows.map((r) => r.label)).toEqual([
      "Subtotal",
      "Delivery",
      "Tax",
      "Total",
    ]);
  });

  it("ALWAYS shows the total, even at zero — it is the number being paid", () => {
    const rows = totalRows(order({ grand_total: "0.00", grand_total_display: "₦0.00" }));

    expect(rows.at(-1)).toEqual({ label: "Total", value: "₦0.00", strong: true });
  });
});
