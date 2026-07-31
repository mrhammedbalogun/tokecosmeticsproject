/**
 * A slug SUGGESTION for the create form.
 *
 * ── IT IS A SUGGESTION, AND THAT IS THE WHOLE DESIGN ────────────────────────────────
 *
 * The field stays editable and the backend decides. This function exists so nobody has to
 * type "carrot-shea-butter" by hand, not so the browser can rule on what a valid slug is —
 * `Product.slug` is a `SlugField(unique=True)` and Django validates both the shape and the
 * uniqueness. A client-side check that disagreed with the database would be worse than
 * none, which is why 17a's spec forbids one for uniqueness specifically.
 *
 * It approximates `django.utils.text.slugify` closely enough to be useful:
 * lowercase, strip accents, drop anything that is not a word character, collapse runs of
 * whitespace and hyphens into one hyphen, trim the ends. Where it differs, the backend
 * wins and says so — which is the same outcome as typing the slug yourself.
 */
export function slugify(value: string): string {
  return (
    value
      .normalize("NFKD")
      // Combining marks, so "Café" becomes "cafe" rather than "caf". `normalize` splits
      // the accent off the letter; this drops the accent and keeps the letter.
      .replace(/[̀-ͯ]/g, "")
      .toLowerCase()
      // Everything Django's first pass removes: not a word character, whitespace, or a
      // hyphen. Note `\w` keeps the underscore, exactly as Django does.
      .replace(/[^\w\s-]/g, "")
      .trim()
      .replace(/[-\s]+/g, "-")
      // Django strips both from the ends.
      .replace(/^[-_]+|[-_]+$/g, "")
  );
}

/** `SlugField` accepts letters, numbers, hyphens and underscores. Used to keep a typo out
 *  of a URL path, never to decide whether the slug is free. */
export const SLUG_PATTERN = /^[-\w]+$/;

export function isSlugShaped(value: string): boolean {
  return SLUG_PATTERN.test(value);
}

/**
 * Whether the slug still tracks the name, so the form knows when to stop auto-filling.
 *
 * Once somebody edits the slug by hand, further typing in the name must leave it alone —
 * silently rewriting a deliberate slug is the kind of thing that gets noticed only after
 * the product is live and the URL is wrong.
 */
export function slugFollowsName(name: string, slug: string): boolean {
  return slug === "" || slug === slugify(name);
}
