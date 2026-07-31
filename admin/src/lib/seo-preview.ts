/**
 * What a search result for this product would actually say.
 *
 * ── THE PREVIEW MUST MIRROR THE STOREFRONT, NOT APPROXIMATE IT ──────────────────────
 *
 * A preview that shows something other than what ships is worse than no preview: somebody
 * trims a title to fit a box that was measuring the wrong string. All three rules below are
 * copied from the storefront and cited, so a change there has a findable counterpart here.
 *
 *   title       `product.seo_title || product.name`
 *               storefront/src/app/(shop)/product/[slug]/page.tsx:39
 *   suffix      `%s | Toke Cosmetics`
 *               storefront/src/app/layout.tsx:21 — the root metadata TEMPLATE, applied to
 *               every page title. Omitting it under-reports the rendered length by 17
 *               characters, which matters precisely when somebody is trimming to fit.
 *   description `product.seo_description || product.short_description`
 *               storefront/src/app/(shop)/product/[slug]/page.tsx:40
 *   url         `/product/<slug>` — note the SINGULAR segment; `/products` is the listing.
 */

export const TITLE_SUFFIX = " | Toke Cosmetics";

/** Where Google starts truncating. Both are approximations by pixel width in reality, but
 *  a character count is the honest, checkable version of the same advice. */
export const TITLE_LIMIT = 60;
export const DESCRIPTION_LIMIT = 155;

export interface SeoPreview {
  /** The full `<title>`, suffix included — what a search engine reads. */
  title: string;
  description: string;
  url: string;
  /** True when the field is empty and the fallback is what would ship. */
  titleIsFallback: boolean;
  descriptionIsFallback: boolean;
  /** True when nothing at all would be rendered — no field, no fallback. */
  descriptionIsEmpty: boolean;
}

export function buildSeoPreview(input: {
  seoTitle: string;
  seoDescription: string;
  name: string;
  shortDescription: string;
  slug: string;
  siteUrl: string;
}): SeoPreview {
  const titleIsFallback = !input.seoTitle.trim();
  const base = titleIsFallback ? input.name : input.seoTitle;

  const descriptionIsFallback = !input.seoDescription.trim();
  const description = descriptionIsFallback ? input.shortDescription : input.seoDescription;

  return {
    title: `${base}${TITLE_SUFFIX}`,
    description,
    url: `${input.siteUrl.replace(/\/$/, "")}/product/${input.slug}`,
    titleIsFallback,
    descriptionIsFallback,
    descriptionIsEmpty: !description.trim(),
  };
}

/** How the text would appear once truncated, with a real ellipsis where one would fall. */
export function truncate(text: string, limit: number): string {
  return text.length <= limit ? text : `${text.slice(0, limit).trimEnd()}…`;
}
