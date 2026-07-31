import { describe, it, expect } from "vitest";
import { NAV_ITEMS, activeHref, visibleNav } from "@/lib/nav";

// The scope sets each seeded role holds, copied from backend/apps/accounts/rbac.py.
// Duplicated deliberately: if the backend table changes, this test should FAIL rather
// than quietly agree with whatever the new table says.
const OWNER = [
  "orders.view", "orders.operate", "orders.manage", "products.manage", "customers.view",
  "marketing.manage", "cms.manage", "reports.view", "staff.manage", "settings.manage",
];
const MANAGER = [
  "orders.view", "orders.operate", "orders.manage", "products.manage", "customers.view",
  "marketing.manage", "reports.view",
];
const SUPPORT = ["orders.view", "orders.operate", "customers.view"];
const CONTENT = ["cms.manage"];

const labels = (scopes: string[]) => visibleNav(scopes).map((i) => i.label);

describe("the sidebar renders only what the scopes allow", () => {
  it("Owner sees everything", () => {
    expect(labels(OWNER)).toEqual(NAV_ITEMS.map((i) => i.label));
  });

  it("Manager sees the trading surfaces but neither Staff nor Settings nor Content", () => {
    expect(labels(MANAGER)).toEqual([
      // Categories carries `products.manage`, the same scope as Products — editing the
      // tree is editing the catalogue, and it is what the storefront nav is built from.
      "Dashboard", "Orders", "Products", "Categories", "Inventory", "Customers", "Reviews",
      "Coupons", "Reports",
    ]);
  });

  it("Support sees orders and customers only", () => {
    expect(labels(SUPPORT)).toEqual(["Dashboard", "Orders", "Customers"]);
  });

  it("Content sees content and reviews", () => {
    expect(labels(CONTENT)).toEqual(["Dashboard", "Reviews", "Content"]);
  });

  it("a staff member with no scopes still sees the dashboard and nothing else", () => {
    expect(labels([])).toEqual(["Dashboard"]);
    expect(visibleNav(undefined).map((i) => i.label)).toEqual(["Dashboard"]);
  });

  it("Staff and Settings are Owner-only — the two surfaces that escalate or move money", () => {
    for (const scopes of [MANAGER, SUPPORT, CONTENT]) {
      expect(labels(scopes)).not.toContain("Staff");
      expect(labels(scopes)).not.toContain("Settings");
    }
  });
});

describe("active-link matching", () => {
  it("highlights the section a nested route belongs to", () => {
    expect(activeHref("/orders/TC-100038")).toBe("/orders");
    expect(activeHref("/settings/audit")).toBe("/settings");
  });
  it("falls back to the dashboard rather than matching everything", () => {
    expect(activeHref("/")).toBe("/");
    expect(activeHref("/something-new")).toBe("/");
  });
});
