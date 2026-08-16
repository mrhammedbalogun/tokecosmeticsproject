import Link from "next/link";

/**
 * The holding screen every `More`-menu page renders until its real content is written.
 *
 * ── WHY A SHARED COMPONENT AND NOT EIGHT COPIES ─────────────────────────────────────
 *
 * `/skin-quiz` and `/blog` each hand-rolled this same markup, and they had already
 * drifted apart in wording. Eight more copies would guarantee that when the placeholder
 * copy is corrected once, seven pages keep the old line. The pages themselves stay as
 * separate files because each will grow its own bespoke layout — a store locator, a
 * careers board — and at that point the page simply stops importing this.
 *
 * Deliberately NOT `noindex`. These are real, permanent URLs that will hold real content
 * shortly; a noindex now would have to be remembered and removed later, and forgetting
 * is the likelier outcome. A thin page ranks poorly, which is the correct outcome for a
 * thin page, and costs nothing else.
 */
export function PagePlaceholder({
  title,
  intro,
  ctaHref = "/products",
  ctaLabel = "Shop all products",
}: {
  title: string;
  /** One sentence saying what this page will hold — not a generic "coming soon". A
   *  visitor who clicked "Careers" should still learn that roles get posted here. */
  intro: string;
  ctaHref?: string;
  ctaLabel?: string;
}) {
  return (
    <div className="mx-auto max-w-2xl px-4 py-24 text-center">
      <h1 className="font-display text-4xl">{title}</h1>
      <p className="mt-4 text-muted">{intro}</p>
      <Link
        href={ctaHref}
        className="mt-8 inline-block rounded-full bg-accent px-8 py-3.5 font-medium text-surface transition hover:bg-accent-strong"
      >
        {ctaLabel}
      </Link>
    </div>
  );
}
