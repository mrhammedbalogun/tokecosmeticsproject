/**
 * The sidebar, and which scopes each item needs.
 *
 * SCOPES, NEVER GROUPS. `/auth/admin-me/` returns scope strings precisely so the role
 * table lives in one codebase (`backend/apps/accounts/rbac.py`) instead of two. Nothing
 * in this app may ever say "if the user is a Manager".
 *
 * NAV FILTERING IS NOT AUTHORIZATION. Hiding a link stops a staff member from wandering
 * into a 403; it stops nobody from typing the URL, and it is not supposed to. Every
 * endpoint behind these pages carries its own `HasAdminScope`, re-read from the database
 * on each request, which is the fence. Treat this list as ergonomics.
 *
 * `scopes` is ANY-OF. Every item names exactly one except `Settings`, which is a door to
 * sections with different owners: Payments and the audit log are `settings.manage`
 * (Owner-only), while Delivery is `products.manage` — the scope the delivery endpoints
 * actually check, because a delivery price is an operational number, not a money-routing
 * decision (see `backend/apps/delivery/admin_views.py`). A Manager therefore gets the
 * door; `/settings` itself then shows only the sections the visitor's scopes cover.
 *
 * `Settings` and `Staff` are real pages as of Task 7; every other href below is a
 * placeholder until Plans 17-19 build it. That is deliberate and matches the plan text:
 * the shell is what Task 5 proves, and Task 7's two pages are what prove the shell holds
 * a real page.
 */
export interface NavItem {
  label: string;
  href: string;
  /** Any one of these grants the item. Empty = always visible to any staff member. */
  scopes: string[];
}

export const NAV_ITEMS: NavItem[] = [
  { label: "Dashboard", href: "/", scopes: [] },
  { label: "Orders", href: "/orders", scopes: ["orders.view"] },
  // A door like Settings (Plan-35): the shipment table is desk reading (`orders.view`),
  // Pickup locations is a Manager's surface (`products.manage`). Any-of; the door page
  // then shows only the sections the visitor's scopes cover.
  { label: "Deliveries", href: "/deliveries", scopes: ["orders.view", "products.manage"] },
  { label: "Products", href: "/products", scopes: ["products.manage"] },
  // Its own item rather than a link inside Products: the tree is a separate job from
  // editing a product, and `activeHref` does longest-prefix matching, so nesting it under
  // `/products/…` would highlight Products while the categories page was on screen.
  { label: "Categories", href: "/categories", scopes: ["products.manage"] },
  { label: "Inventory", href: "/inventory", scopes: ["products.manage"] },
  // The public store locator's directory (Plan-42). `products.manage` for the same
  // reason Pickup locations is: it is a list of physical shops maintained by whoever
  // runs the day to day. Top-level rather than under Deliveries, because nothing in it
  // ships anything — an active row here is a shop a customer walks into, and filing it
  // beside the carrier screens is how somebody eventually confuses the two.
  { label: "Find a Store", href: "/find-stores", scopes: ["products.manage"] },
  { label: "Customers", href: "/customers", scopes: ["customers.view"] },
  { label: "Reviews", href: "/reviews", scopes: ["reviews.manage"] },
  { label: "Coupons", href: "/coupons", scopes: ["marketing.manage"] },
  // One door for everything the landing page shows (Hammed's ask, 2026-08-05):
  // slides, news, reviews and the product-row collections, in section order.
  { label: "Home Content", href: "/home-content", scopes: ["marketing.manage"] },
  // Sits next to Home Content because it is the same job — banner artwork — on a
  // different page, and it is scoped `marketing.manage` for the same reason. It gets a
  // nav item of its own rather than living as a link inside Content because Content is
  // `cms.manage`: a marketer who can upload this artwork may never see that door at all,
  // and hiding the only route to it behind a scope they lack is how it stayed
  // unreachable until 2026-08-16.
  { label: "Affiliates page", href: "/content/affiliates", scopes: ["marketing.manage"] },
  { label: "Content", href: "/content", scopes: ["cms.manage"] },
  // Support sees it too — `referrals.view` — because "where is my commission?" arrives at
  // the same desk as "where is my order?". Deciding and paying carry their own scopes on
  // the endpoints; this item is only the door.
  { label: "Referrals", href: "/referrals", scopes: ["referrals.view"] },
  { label: "Reports", href: "/reports", scopes: ["reports.view"] },
  { label: "Settings", href: "/settings", scopes: ["settings.manage", "products.manage"] },
  { label: "Staff", href: "/staff", scopes: ["staff.manage"] },
  // Owner-only, like Staff above, and top-level for the same reason: it is a list of
  // people and what reaches them, and it is the screen somebody opens when an alert did
  // not arrive — a moment for one click rather than two through the Settings door.
  { label: "Email Notifications", href: "/notifications", scopes: ["settings.manage"] },
];

export function visibleNav(scopes: readonly string[] | undefined): NavItem[] {
  const held = new Set(scopes ?? []);
  return NAV_ITEMS.filter(
    (item) => item.scopes.length === 0 || item.scopes.some((s) => held.has(s)),
  );
}

/** Longest-prefix match, so `/orders/42` highlights `Orders` and not `Dashboard`.
 *
 * ACTUALLY LONGEST, not last-in-the-array. This used to return the final match in
 * `NAV_ITEMS` order, which gave the right answer only because no nested pair existed
 * where the parent was declared after the child. `/content/affiliates` (2026-08-16) is
 * declared before `/content`, so both matched and the parent won: the sidebar lit up
 * "Content" while the Affiliates page was on screen. Sorting by href length makes the
 * behaviour match the sentence above regardless of declaration order.
 */
export function activeHref(pathname: string): string {
  const matches = NAV_ITEMS.filter(
    (item) => item.href !== "/" && (pathname === item.href || pathname.startsWith(`${item.href}/`)),
  );
  if (!matches.length) return "/";
  return matches.reduce((best, item) =>
    item.href.length > best.href.length ? item : best,
  ).href;
}
