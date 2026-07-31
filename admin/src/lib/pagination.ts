/**
 * Pagination arithmetic, shared by every paged admin list.
 *
 * Extracted from `lib/audit.ts` in Plan-17a Task 2, when the products list became the
 * second consumer. `lib/audit.ts` re-exports these so nothing that imported them from
 * there had to move, and so there is still exactly one implementation of each.
 */

/** Mirrors DRF's `PAGE_SIZE` in `backend/config/settings/base.py`. If that changes, the
 *  page numbers rendered here stop lining up with the pages the API returns. */
export const PAGE_SIZE = 24;

export function pageCount(total: number): number {
  // An empty list is one empty page, not zero pages: "Page 1 of 0" is nonsense on screen.
  return Math.max(1, Math.ceil(total / PAGE_SIZE));
}

/**
 * The page numbers to render, with `"…"` standing in for a run of hidden pages.
 *
 * A gap marker is only used where it hides MORE THAN ONE page — `1 … 3` is both longer
 * than `1 2 3` and a click worse.
 */
export function pageWindow(current: number, total: number): (number | "…")[] {
  const pages = new Set<number>([1, total]);
  for (let p = current - 1; p <= current + 1; p++) {
    if (p >= 1 && p <= total) pages.add(p);
  }
  const sorted = [...pages].sort((a, b) => a - b);

  const out: (number | "…")[] = [];
  let previous = 0;
  for (const page of sorted) {
    const skipped = page - previous - 1;
    if (previous !== 0 && skipped > 0) {
      // Exactly one page hidden → render it instead of a marker.
      if (skipped === 1) out.push(page - 1);
      else out.push("…");
    }
    out.push(page);
    previous = page;
  }
  return out;
}
