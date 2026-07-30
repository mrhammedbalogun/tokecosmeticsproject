/**
 * Page links for the audit log.
 *
 * A SERVER COMPONENT — no `"use client"`. Every control here is an anchor, so there is
 * nothing to hydrate, and paging a table by navigation rather than by state means the
 * URL is always the truth about what is on screen. That is worth more here than anywhere
 * else in the app: "send me the link to what you were looking at" is the normal way an
 * audit finding gets shared.
 *
 * EVERY LINK CARRIES THE ACTIVE FILTERS. Dropping them on page 2 would be invisible —
 * page 2 of a filtered log and page 2 of the whole log look the same — so
 * `auditQueryString` builds every href from the same filters the page was rendered with.
 */
import Link from "next/link";
import { auditQueryString, pageCount, pageWindow, type AuditFilters } from "@/lib/audit";

interface Props {
  basePath: string;
  filters: AuditFilters;
  /** Total row count from the API's `count`, or the page total when already computed. */
  total: number;
  /** Set when `total` is already a page count rather than a row count. */
  totalIsPages?: boolean;
}

export function Pagination({ basePath, filters, total, totalIsPages = true }: Props) {
  const pages = totalIsPages ? Math.max(1, total) : pageCount(total);
  // One page means no navigation to offer. Rendering a lone disabled "1" is furniture.
  if (pages <= 1) return null;

  const href = (page: number) => {
    const qs = auditQueryString({ ...filters, page });
    return qs ? `${basePath}?${qs}` : basePath;
  };

  return (
    <nav aria-label="Audit log pages" className="mt-4 flex flex-wrap items-center gap-1">
      {pageWindow(filters.page, pages).map((entry, index) =>
        entry === "…" ? (
          <span key={`gap-${index}`} aria-hidden="true" className="px-2 text-sm text-muted">
            …
          </span>
        ) : entry === filters.page ? (
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
