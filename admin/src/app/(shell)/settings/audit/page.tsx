import type { Metadata } from "next";
import { AuditFilterForm } from "@/components/AuditFilterForm";
import { AuditTable } from "@/components/AuditTable";
import { Pagination } from "@/components/Pagination";
import { ApiError } from "@/lib/api";
import { auditQueryString, pageCount, parseAuditFilters, type AuditPage } from "@/lib/audit";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";

export const metadata: Metadata = { title: "Audit log" };

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

const PATH = "/settings/audit";

/**
 * `/settings/audit` — the read side of the audit log, behind `settings.manage`.
 *
 * THE PAGE ITSELF IS NOT THE AUTHORIZATION. `requireAdmin` establishes a session and
 * nothing more; whether this person may READ the log is decided by `HasAdminScope
 * ("settings.manage")` on the endpoint, on every request, from the database. A staff
 * member without the scope who types this URL gets a session, a page, and a 403 from the
 * API — which this renders as a message rather than as a crash, because "you may not see
 * this" is an answer and a stack trace is not.
 *
 * FETCHED THROUGH `fetchWithAuthOrBounce`, never `fetchWithAuth`: this is a Server
 * Component, and a Server Component cannot persist a rotated refresh token. Calling the
 * writing fetcher here would blacklist the old token server-side with nowhere to put the
 * new one — a silently ended session. `lib/session.ts` has a dev-time tripwire for
 * exactly this mistake; the right call is the bouncing one.
 *
 * NOTE THAT LOADING THIS PAGE WRITES AN AUDIT ROW. `AuditLogListView` is read-audited on
 * purpose — "who has been reading the log, and what were they searching for" is the
 * behaviour that precedes somebody deciding which rows to remove. Paging through the log
 * therefore appears in the log. That is intended, not a loop: one read makes one row, and
 * that row records the query parameters, never the rows returned.
 */
export default async function AuditPage({ searchParams }: { searchParams: SearchParams }) {
  await requireAdmin(PATH);

  const raw = new URLSearchParams();
  for (const [key, value] of Object.entries(await searchParams)) {
    if (typeof value === "string") raw.set(key, value);
    else if (Array.isArray(value) && value[0] !== undefined) raw.set(key, value[0]);
  }
  const filters = parseAuditFilters(raw);

  let page: AuditPage | null = null;
  let error: string | null = null;
  try {
    const qs = auditQueryString(filters);
    page = await fetchWithAuthOrBounce<AuditPage>(`/admin/audit/${qs ? `?${qs}` : ""}`, PATH);
  } catch (e) {
    // `redirect()` works by THROWING, so a bare catch-all here would swallow the renewal
    // bounce and render an error page to somebody whose session was merely stale.
    if (!(e instanceof ApiError)) throw e;
    if (e.status === 403) {
      error = "Your role does not include access to the audit log.";
    } else if (e.status === 400) {
      // The realistic 400 is a timestamp the backend could not parse — its own message
      // is specific and useful, so it is shown rather than replaced.
      error = e.message || "One of those filters was not understood.";
    } else {
      error = "The audit log could not be loaded.";
    }
  }

  const rows = page?.results ?? [];
  // The dropdown is populated from what is ON THIS PAGE, which is honest about its
  // limits: it offers the actions actually present rather than a hardcoded vocabulary
  // that would drift from whatever the backend writes.
  const actions = [...new Set(rows.map((row) => row.action))].sort();

  return (
    <div>
      <h1 className="text-lg font-semibold tracking-tight">Audit log</h1>
      <p className="mt-1 text-sm text-muted">
        Every write on the admin surface, and the reads that touch personal data. Entries
        cannot be edited or deleted — including by you.
      </p>

      <div className="mt-6">
        <AuditFilterForm filters={filters} actions={actions} />

        {error ? (
          <p className="rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-4 text-sm text-warn">
            {error}
          </p>
        ) : (
          <>
            <p className="mb-2 text-xs text-muted">
              {page?.count ?? 0} {page?.count === 1 ? "entry" : "entries"}
            </p>
            <AuditTable rows={rows} />
            <Pagination
              basePath={PATH}
              filters={filters}
              total={pageCount(page?.count ?? 0)}
            />
          </>
        )}
      </div>
    </div>
  );
}
