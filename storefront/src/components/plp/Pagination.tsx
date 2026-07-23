import Link from "next/link";
import { plpHref, type PlpState } from "@/components/plp/plpParams";

/** Prev/Next are driven by the API's own `next`/`previous` links (from the
 * Paginated response), not a computed page count — so we never link to a page
 * beyond the last (which DRF 404s) and there is no hardcoded page-size coupling. */
export function Pagination({ base, state, hasPrev, hasNext }: {
  base: string; state: PlpState; hasPrev: boolean; hasNext: boolean;
}) {
  if (!hasPrev && !hasNext) return null;
  const page = state.page;
  return (
    <nav aria-label="Pagination" className="mt-10 flex items-center justify-center gap-2">
      {hasPrev && (
        <Link rel="prev" href={plpHref(base, state, { page: page - 1 })}
          className="rounded-full border border-line px-4 py-2 text-sm hover:border-accent">← Prev</Link>
      )}
      <span className="px-3 text-sm text-muted">Page {page}</span>
      {hasNext && (
        <Link rel="next" href={plpHref(base, state, { page: page + 1 })}
          className="rounded-full border border-line px-4 py-2 text-sm hover:border-accent">Next →</Link>
      )}
    </nav>
  );
}
