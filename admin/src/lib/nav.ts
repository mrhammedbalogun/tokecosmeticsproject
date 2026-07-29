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
 * `scopes` is ANY-OF. Most items name one; `Reviews` names two because review moderation
 * genuinely straddles catalogue management and content integrity, and the scope table has
 * no review-specific scope to point at. When Plan-18/19 bind those endpoints to a scope,
 * this entry should be narrowed to match whatever they choose rather than left to drift.
 *
 * Every href below except `/` is a placeholder until Plans 17-19 build the page. That is
 * deliberate and matches the plan text: the shell is what Task 5 proves.
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
  { label: "Products", href: "/products", scopes: ["products.manage"] },
  { label: "Inventory", href: "/inventory", scopes: ["products.manage"] },
  { label: "Customers", href: "/customers", scopes: ["customers.view"] },
  { label: "Reviews", href: "/reviews", scopes: ["products.manage", "cms.manage"] },
  { label: "Coupons", href: "/coupons", scopes: ["marketing.manage"] },
  { label: "Content", href: "/content", scopes: ["cms.manage"] },
  { label: "Reports", href: "/reports", scopes: ["reports.view"] },
  { label: "Settings", href: "/settings", scopes: ["settings.manage"] },
  { label: "Staff", href: "/staff", scopes: ["staff.manage"] },
];

export function visibleNav(scopes: readonly string[] | undefined): NavItem[] {
  const held = new Set(scopes ?? []);
  return NAV_ITEMS.filter(
    (item) => item.scopes.length === 0 || item.scopes.some((s) => held.has(s)),
  );
}

/** Longest-prefix match, so `/orders/42` highlights `Orders` and not `Dashboard`. */
export function activeHref(pathname: string): string {
  const matches = NAV_ITEMS.filter(
    (item) => item.href !== "/" && (pathname === item.href || pathname.startsWith(`${item.href}/`)),
  );
  return matches.length ? matches[matches.length - 1].href : "/";
}
