import Link from "next/link";

/**
 * Prev/Next markup, shared by the PLP and the account orders list. Purely
 * presentational: it takes finished hrefs and never builds one.
 *
 * HREF BUILDING STAYS WITH THE CALLER on purpose — the two callers canonicalise
 * differently (the PLP drops the param entirely for page 1 so `/products` and
 * `/products?page=1` are not two URLs competing for the same index entry; the orders list
 * has nothing to index and emits `?page=1` plainly). Folding that into here would force
 * one rule onto both and quietly change PLP's canonical URLs.
 *
 * A null href hides its link, which is how a caller expresses "the API reported no
 * next/previous page" — never a computed page count, so we cannot link past the last page
 * (which DRF 404s).
 */
export function Pagination({ page, prevHref, nextHref }: {
  page: number; prevHref: string | null; nextHref: string | null;
}) {
  if (prevHref === null && nextHref === null) return null;
  return (
    <nav aria-label="Pagination" className="mt-10 flex items-center justify-center gap-2">
      {prevHref !== null && (
        <Link rel="prev" href={prevHref}
          className="rounded-full border border-line px-4 py-2 text-sm hover:border-accent">← Prev</Link>
      )}
      <span className="px-3 text-sm text-muted">Page {page}</span>
      {nextHref !== null && (
        <Link rel="next" href={nextHref}
          className="rounded-full border border-line px-4 py-2 text-sm hover:border-accent">Next →</Link>
      )}
    </nav>
  );
}
