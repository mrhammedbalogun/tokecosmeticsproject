/** The Toke Cosmetics social accounts — ONE definition, imported by everything.
 *
 * WHY THIS FILE EXISTS. These lived in two places, `Footer.tsx` and `seo.ts`, and they
 * drifted: the footer and the structured data both pointed at `instagram.com/tokecosmetics`
 * while the real account is `tokecosmetics_brand`, and neither knew about the YouTube
 * channel at all. Two copies of a URL is two chances to be wrong, and the `sameAs` copy is
 * the one nobody looks at — it is read by search engines, not people, so a stale entry
 * there can sit wrong indefinitely. Corrected 2026-08-18 from the owner's own list.
 *
 * The ICONS are not here. They are JSX paths and belong with the component that draws
 * them; this file is the data, keyed by label so `Footer.tsx` can look one up.
 *
 * KEEP IN STEP WITH `backend/apps/notifications/branding.py`, which holds the same list
 * for the transactional emails. TypeScript cannot import Python and vice versa, so the
 * duplication is unavoidable — but the two files are each a single source for their own
 * side, and changing one means changing the other.
 */
export interface SocialLink {
  label: string;
  href: string;
}

/** Order matters — it is the order they render in the footer, biggest audience first. */
export const SOCIAL_LINKS: readonly SocialLink[] = [
  { label: "Instagram", href: "https://www.instagram.com/tokecosmetics_brand/" },
  { label: "TikTok", href: "https://www.tiktok.com/@tokecosmetics" },
  { label: "Facebook", href: "https://www.facebook.com/tokecosmetics" },
  { label: "YouTube", href: "https://www.youtube.com/@tokecosmetics" },
] as const;
