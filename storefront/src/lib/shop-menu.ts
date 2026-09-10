/**
 * The "Shop by Category" menu: one model, rendered by both the desktop mega-panel and the
 * mobile drawer.
 *
 * ── WHERE THE MENU COMES FROM ───────────────────────────────────────────────────────────
 *
 * Mostly from the CATEGORY TREE, so staff reshape the menu by editing categories in the
 * admin — rename "Facial Care", reorder it, hide it — with no deploy. `sort_order` decides
 * position, and a category with `is_assignable: false` is a GROUP HEADING: it holds no
 * products of its own, it exists to gather the ones under it.
 *
 * One group is not in the tree at all. "Shop By Edit" is five COMPUTED listings —
 * best sellers by units sold, newest first, whatever is reduced today, the combo page,
 * and a shortcut to Travel Sizes. None of them is a set a product gets filed into, so
 * making them categories would mean an admin picker offering "Best Sellers" as a checkbox
 * and a page showing whichever products somebody happened to tick. They live here instead,
 * and `EDIT_GROUP` is the whole definition.
 *
 * ── WHY THE HEADINGS ARE STILL LINKS ────────────────────────────────────────────────────
 *
 * "Shop By Skin Concerns" links to its own page, which lists every product under Acne,
 * Dry Skin, Hyperpigmentation and Oily Skin (the API's `?category=` matches the subtree).
 * A shopper who clicks a group name expects a shop, not a menu that swallows the click.
 * "Shop By Edit" is the one group with no link of its own, because it has no page: its
 * entries are five separate listings and there is no "all of Shop By Edit".
 */
import type { CategoryNode } from "@/lib/catalog";

export interface MenuLink {
  label: string;
  href: string;
  /** Short line under the label in the desktop panel. Only the computed edits have one —
   *  "Best Sellers" needs saying what it means; "Hair Care" does not. */
  note?: string;
}

export interface MenuGroup {
  label: string;
  /** The group's own page, or null when the group is a label only ("Shop By Edit"). */
  href: string | null;
  links: MenuLink[];
}

/** A top-level entry is either a single link or a group with children. */
export type MenuEntry =
  | { kind: "link"; link: MenuLink }
  | { kind: "group"; group: MenuGroup };

/** Where "Shop By Edit › Travel Sizes" points. It is a real category — the only entry in
 *  that group that is — so the link is built from the tree rather than hardcoded, and
 *  disappears with the category if staff ever hide it. */
const TRAVEL_SIZES_SLUG = "travel-sizes";

/**
 * "Shop By Edit", in menu order. `href` is a route, not a category.
 *
 * Combo Deals points at the existing `/combo` page rather than a listing of its own: a
 * combo is not a product and does not appear in `/products` at all.
 */
const EDIT_GROUP: MenuLink[] = [
  { label: "Best Sellers", href: "/best-sellers", note: "What everyone is buying" },
  { label: "New Arrivals", href: "/new-arrivals", note: "Newest in the shop" },
  { label: "Promo", href: "/promo", note: "Reduced right now" },
  { label: "Combo Deals", href: "/combo", note: "Sets, priced below separate" },
];

export const EDIT_GROUP_LABEL = "Shop By Edit";

/** Href for a category, in one place so the menu, the group headings and the breadcrumbs
 *  cannot drift apart. */
export const categoryHref = (slug: string) => `/category/${slug}`;

/**
 * Build the menu from the category tree.
 *
 * Ordering is the API's (`sort_order`, then name) and is not re-sorted here — one source
 * of truth for position, editable in the admin. "Shop By Edit" is inserted at
 * `editPosition`, counted in top-level entries, so it sits seventh as approved while
 * remaining robust if a category is added or hidden: a menu of four entries puts it last
 * rather than dropping it.
 *
 * A childless HEADING is dropped rather than shown as an empty flyout — the state between
 * creating "Shop By Skin Tone" and adding the first tone to it. A childless ordinary
 * category is a plain link, which is what four of the eight entries are.
 */
export function buildShopMenu(tree: CategoryNode[], editPosition = 6): MenuEntry[] {
  const entries: MenuEntry[] = tree.flatMap((node): MenuEntry[] => {
    const children = node.children ?? [];
    if (children.length === 0) {
      // A heading with nothing under it is dropped, not linked: `is_assignable: false`
      // means no product can be filed there either, so its page would be empty. This is
      // the state between creating "Shop By Skin Tone" and adding the first tone to it.
      if (node.is_assignable === false) return [];
      return [{ kind: "link", link: { label: node.name, href: categoryHref(node.slug) } }];
    }
    return [{
      kind: "group",
      group: {
        label: node.name,
        href: categoryHref(node.slug),
        links: children.map((child) => ({
          label: child.name,
          href: categoryHref(child.slug),
        })),
      },
    }];
  });

  const travelSizes = tree.find((node) => node.slug === TRAVEL_SIZES_SLUG);
  const editLinks: MenuLink[] = [
    ...EDIT_GROUP,
    ...(travelSizes
      ? [{
          label: travelSizes.name,
          href: categoryHref(travelSizes.slug),
          note: "Small enough to fly",
        }]
      : []),
  ];

  const at = Math.min(Math.max(editPosition, 0), entries.length);
  entries.splice(at, 0, {
    kind: "group",
    // No href: the group is a label. Its five entries are computed listings, so there is
    // no "all of Shop By Edit" page for it to point at.
    group: { label: EDIT_GROUP_LABEL, href: null, links: editLinks },
  });
  return entries;
}

/** Flat list of every destination in the menu — used by the sitemap and by tests that
 *  assert nothing in the menu 404s. */
export function menuHrefs(entries: MenuEntry[]): string[] {
  const out: string[] = [];
  for (const entry of entries) {
    if (entry.kind === "link") out.push(entry.link.href);
    else {
      if (entry.group.href) out.push(entry.group.href);
      out.push(...entry.group.links.map((l) => l.href));
    }
  }
  return [...new Set(out)];
}
