import { describe, it, expect } from "vitest";
import { NAV_ITEMS, activeHref, visibleNav } from "@/lib/nav";

// The scope sets each seeded role holds, copied from backend/apps/accounts/rbac.py.
// Duplicated deliberately: if the backend table changes, this test should FAIL rather
// than quietly agree with whatever the new table says.
const OWNER = [
  "orders.view", "orders.operate", "orders.manage", "products.manage", "reviews.manage",
  "customers.view", "marketing.manage", "cms.manage", "reports.view", "staff.manage",
  "settings.manage", "referrals.view", "referrals.manage", "referrals.pay",
];
const MANAGER = [
  "orders.view", "orders.operate", "orders.manage", "products.manage", "reviews.manage",
  "customers.view", "marketing.manage", "reports.view", "referrals.view",
  "referrals.manage", "referrals.pay",
];
const SUPPORT = ["orders.view", "orders.operate", "customers.view", "referrals.view"];
const CONTENT = ["cms.manage"];

const labels = (scopes: string[]) => visibleNav(scopes).map((i) => i.label);

describe("activeHref picks the LONGEST matching item, not the last declared", () => {
  it("highlights the child, not its parent", () => {
    // `/content/affiliates` is declared BEFORE `/content`, and the old implementation
    // returned the last match in array order — so the sidebar lit "Content" while the
    // Affiliates page was on screen. Declaration order must not decide this.
    expect(activeHref("/content/affiliates")).toBe("/content/affiliates");
    expect(activeHref("/content")).toBe("/content");
    expect(activeHref("/content/some-slug")).toBe("/content");
  });

  it("still resolves the ordinary nested cases", () => {
    expect(activeHref("/orders/42")).toBe("/orders");
    expect(activeHref("/deliveries/pickup-locations")).toBe("/deliveries");
    expect(activeHref("/nowhere")).toBe("/");
  });
});

describe("the sidebar renders only what the scopes allow", () => {
  it("Owner sees everything", () => {
    expect(labels(OWNER)).toEqual(NAV_ITEMS.map((i) => i.label));
  });

  it("Manager sees the trading surfaces plus Settings, but neither Staff nor Content", () => {
    expect(labels(MANAGER)).toEqual([
      // Categories carries `products.manage`, the same scope as Products — editing the
      // tree is editing the catalogue, and it is what the storefront nav is built from.
      "Dashboard", "Orders", "Deliveries", "Products", "Categories", "Inventory",
      "Customers", "Reviews",
      "Coupons",
      "Home Content",
      // Same `marketing.manage` as Home Content — it is the same job (banner artwork) on
      // a different page. It is NOT under Content, which is `cms.manage`: a marketer who
      // can upload this artwork may not hold that scope, and putting the only route to it
      // behind a door they cannot open is how it went unreachable in the first place.
      "Affiliates page",
      // `referrals.view` — a Manager reads the payout queue, decides requests, and
      // (Hammed's ruling, 2026-08-15) holds `referrals.pay` too: the Manager runs the
      // monthly transfers. The scopes live on the endpoints, not the nav.
      "Referrals",
      "Reports",
      // Settings is any-of `settings.manage` / `products.manage`: the Delivery section
      // runs on `products.manage`, so a Manager gets the door. The index page then shows
      // only Delivery; Payments and Audit stay behind `settings.manage`.
      "Settings",
    ]);
  });

  it("Support sees orders, deliveries and customers only", () => {
    // Deliveries opens on `orders.view` — the shipment table is desk reading; the
    // door page then hides the Pickup-locations card Support cannot use.
    // Referrals is on the list for the same reason Orders is: the desk answers "where
    // is my commission?" and needs to see the request without being able to decide it.
    expect(labels(SUPPORT)).toEqual([
      "Dashboard", "Orders", "Deliveries", "Customers", "Referrals",
    ]);
  });

  it("Content sees content only — customer reviews are shop management, not copy", () => {
    expect(labels(CONTENT)).toEqual(["Dashboard", "Content"]);
  });

  it("a staff member with no scopes still sees the dashboard and nothing else", () => {
    expect(labels([])).toEqual(["Dashboard"]);
    expect(visibleNav(undefined).map((i) => i.label)).toEqual(["Dashboard"]);
  });

  it("Staff stays Owner-only, and Settings opens to nobody below Manager", () => {
    for (const scopes of [MANAGER, SUPPORT, CONTENT]) {
      expect(labels(scopes)).not.toContain("Staff");
    }
    for (const scopes of [SUPPORT, CONTENT]) {
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
