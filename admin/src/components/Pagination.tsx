/**
 * Page links for any paged admin list.
 *
 * A SERVER COMPONENT — no `"use client"`. Every control here is an anchor, so there is
 * nothing to hydrate, and paging a table by navigation rather than by state means the URL
 * is always the truth about what is on screen. That is worth most on the audit log, where
 * "send me the link to what you were looking at" is the normal way a finding gets shared.
 *
 * EVERY LINK MUST CARRY THE ACTIVE FILTERS, which is why the caller supplies `buildQuery`
 * rather than this component knowing about any particular filter shape. Dropping filters
 * on page 2 would be invisible — page 2 of a filtered list and page 2 of the whole list
 * look identical — so each list builds its hrefs from the same filters it rendered with,
 * through its own query-string function.
 *
 * Generalised in Plan-17a Task 2. It previously imported `AuditFilters` and
 * `auditQueryString` directly, which made a second paged list impossible without either
 * duplicating this file or teaching the audit query-string builder about products.
 */
import Link from "next/link";
import { pageCount, pageWindow } from "@/lib/pagination";

interface Props {
  basePath: string;
  /** The page currently on screen. */
  page: number;
  /** Total row count from the API's `count`, or a page count when `totalIsPages`. */
  total: number;
  /** Set when `total` is already a page count rather than a row count. */
  totalIsPages?: boolean;
  /** The query string for a given page, filters included. Omit the leading `?`. */
  buildQuery: (page: number) => string;
  /** For the landmark's accessible name — there can be two paged lists in one app. */
  label?: string;
}

export function Pagination({
  basePath,
  page,
  total,
  totalIsPages = true,
  buildQuery,
  label = "Pages",
}: Props) {
  const pages = totalIsPages ? Math.max(1, total) : pageCount(total);
  // One page means no navigation to offer. Rendering a lone disabled "1" is furniture.
  if (pages <= 1) return null;

  const href = (target: number) => {
    const qs = buildQuery(target);
    return qs ? `${basePath}?${qs}` : basePath;
  };

  return (
    <nav aria-label={label} className="mt-4 flex flex-wrap items-center gap-1">
      {pageWindow(page, pages).map((entry, index) =>
        entry === "…" ? (
          <span key={`gap-${index}`} aria-hidden="true" className="px-2 text-sm text-muted">
            …
          </span>
        ) : entry === page ? (
          <span
            key={entry}
            aria-current="page"
            className="rounded border border-accent bg-accent/10 px-3 py-1 text-sm font-medium"
          >
            {entry}
          </span>
        ) : (
          <Link
            key={entry}
            href={href(entry)}
            aria-label={`Page ${entry}`}
            className="rounded border border-line px-3 py-1 text-sm hover:border-accent"
          >
            {entry}
          </Link>
        ),
      )}
    </nav>
  );
}
