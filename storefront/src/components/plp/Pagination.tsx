import { plpHref, type PlpState } from "@/components/plp/plpParams";
import { Pagination as PaginationView } from "@/components/ui/Pagination";

/** The PLP's href-building wrapper around the shared Prev/Next markup. Prev/Next are
 * driven by the API's own `next`/`previous` links (from the Paginated response), not a
 * computed page count — so we never link to a page beyond the last (which DRF 404s) and
 * there is no hardcoded page-size coupling. `plpHref` keeps the PLP's own canonical URL
 * rules (filters carried through, page 1 param-less); the shared view knows none of that. */
export function Pagination({ base, state, hasPrev, hasNext }: {
  base: string; state: PlpState; hasPrev: boolean; hasNext: boolean;
}) {
  return (
    <PaginationView
      page={state.page}
      prevHref={hasPrev ? plpHref(base, state, { page: state.page - 1 }) : null}
      nextHref={hasNext ? plpHref(base, state, { page: state.page + 1 }) : null}
    />
  );
}
