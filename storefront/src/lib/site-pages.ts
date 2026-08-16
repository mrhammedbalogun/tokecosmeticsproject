/** The "More" nav menu — one list, three consumers.
 *
 * `MoreMenu` (desktop dropdown), `MobileNav` (drawer section) and `sitemap.ts` all read
 * this array, so a link is added, renamed or reordered in exactly one place. Before this
 * existed the header and the drawer each held their own hand-written copy of the nav and
 * had already drifted (the drawer was missing "Shop by Category" as a link at all).
 *
 * ── THESE ARE CODE ROUTES, NOT CMS PAGES ────────────────────────────────────────────
 *
 * Every `href` below resolves to a real file under `app/(shop)/`, NOT to `/page/{slug}`.
 * That is deliberate (Hammed's ruling, 2026-08-16): these pages get bespoke layouts —
 * a store locator, a careers board, an affiliate pitch — which a sanitised HTML blob in
 * `Page.body` cannot express. The CMS `Page` model stays for policy text.
 *
 * So adding an entry here WITHOUT adding `app/(shop)/{slug}/page.tsx` ships a nav link
 * to a 404. `src/lib/__tests__/site-pages.test.ts` fails if the two ever disagree.
 */
export interface NavLink {
  readonly label: string;
  readonly href: string;
  /** Sitemap priority. These are supporting pages, not the shop, so all sit below the
   *  0.7 a product gets — Blog is highest because it is the only one that gains content
   *  over time. */
  readonly priority: number;
}

export const MORE_LINKS: readonly NavLink[] = [
  { label: "About Us", href: "/about-us", priority: 0.6 },
  { label: "Contact Us", href: "/contact-us", priority: 0.6 },
  { label: "Blog", href: "/blog", priority: 0.7 },
  { label: "Careers", href: "/careers", priority: 0.4 },
  { label: "Find Stores", href: "/find-stores", priority: 0.5 },
  { label: "Affiliates", href: "/affiliates", priority: 0.5 },
  { label: "Entrepreneurial Program", href: "/entrepreneurial-program", priority: 0.5 },
  { label: "Disclaimer", href: "/disclaimer", priority: 0.3 },
  { label: "Follow Us", href: "/follow-us", priority: 0.4 },
] as const;

/** The label on the trigger. Named rather than inlined so the desktop dropdown and the
 *  mobile drawer heading can never say different things. */
export const MORE_MENU_LABEL = "More";
