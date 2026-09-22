import type { Metadata } from "next";
import Link from "next/link";
import { Pagination } from "@/components/Pagination";
import { Tabs } from "@/app/(shell)/careers/page";
import { ApiError } from "@/lib/api";
import { getAdminMeOrNull } from "@/lib/admin-me";
import {
  APPLICATION_STATUSES,
  applicationsQueryString,
  parseApplicationFilters,
  type ApplicationRow,
  type ApplicationStats,
  type Page,
} from "@/lib/careers";
import { pageCount } from "@/lib/pagination";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";

export const metadata: Metadata = { title: "Applications" };

const PATH = "/careers/applications";

/**
 * `/careers/applications` — who applied, scoped `careers.applications.manage`.
 *
 * ── THIS SCREEN'S READS ARE AUDITED, AND THAT IS DELIBERATE ─────────────────────────
 *
 * Every row here is a named stranger's email, phone number and CV. The backend sets
 * `audit_reads = True` on the viewset, and the guard in
 * `apps/core/tests/test_audit_guard.py` enforces it by matching the scope prefix — so
 * opening this list, and opening any CV from it, both leave a row saying who did.
 *
 * ── THE LIST CARRIES NO COVER LETTERS ───────────────────────────────────────────────
 *
 * The API does not serve them here, only a `has_cover_letter` flag. Shipping every
 * candidate's letter in one paginated response is bulk egress of exactly the kind the
 * audit flag exists to record; a reviewer reads them one at a time anyway.
 */
type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export default async function ApplicationsPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  await requireAdmin(PATH);

  const raw = new URLSearchParams();
  for (const [key, value] of Object.entries(await searchParams)) {
    if (typeof value === "string") raw.set(key, value);
    else if (Array.isArray(value) && value[0] !== undefined) raw.set(key, value[0]);
  }
  const filters = parseApplicationFilters(raw);
  // Only to decide whether the Notifications tab is offered — the scope is re-checked on
  // every request behind it.
  const scopes = new Set((await getAdminMeOrNull())?.scopes ?? []);

  let page: Page<ApplicationRow> | null = null;
  let stats: ApplicationStats | null = null;
  let error: string | null = null;
  try {
    const query = applicationsQueryString(filters);
    const [rows, counts] = await Promise.all([
      fetchWithAuthOrBounce<Page<ApplicationRow>>(
        `/admin/careers/applications/${query ? `?${query}` : ""}`,
        PATH,
      ),
      // The counts degrade rather than failing the page — losing the chips costs a
      // filter, throwing costs the applications.
      fetchWithAuthOrBounce<ApplicationStats>(
        "/admin/careers/applications/stats/",
        PATH,
      ).catch(() => null),
    ]);
    page = rows;
    stats = counts;
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    error =
      e.status === 403
        ? "Your role does not include reading job applications."
        : "The applications could not be loaded.";
  }

  return (
    <div>
      <h1 className="text-lg font-semibold tracking-tight">Careers</h1>
      <p className="mt-1 text-sm text-muted">
        Everyone who has applied through the careers page.
      </p>
      <Tabs
        active="applications"
        canSeeApplications
        canSeeNotifications={scopes.has("careers.notifications.manage")}
      />

      <div className="mt-6">
        {error ? (
          <p className="rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-4 text-sm text-warn">
            {error}
          </p>
        ) : (
          <>
            {stats && stats.total > 0 && (
              <p className="mb-4 text-sm">
                <span className="font-medium">{stats.total}</span> in total
                {stats.new > 0 && (
                  <>
                    {" · "}
                    <span className="font-medium text-accent">{stats.new}</span> waiting
                    to be looked at
                  </>
                )}
              </p>
            )}

            <Filters filters={filters} stats={stats} />

            {(page?.results ?? []).length === 0 ? (
              <p className="rounded-[var(--radius-card)] border border-line bg-surface p-8 text-center text-sm text-muted">
                {filters.job || filters.status || filters.q
                  ? "Nothing matches those filters."
                  : "No applications yet. They appear here the moment somebody applies."}
              </p>
            ) : (
              <div className="overflow-x-auto rounded-[var(--radius-card)] border border-line bg-surface">
                <table className="w-full min-w-[820px] text-sm">
                  <thead className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
                    <tr>
                      <th className="px-4 py-3 font-medium">Candidate</th>
                      <th className="px-4 py-3 font-medium">Role</th>
                      <th className="px-4 py-3 font-medium">Applied</th>
                      <th className="px-4 py-3 font-medium">Status</th>
                      <th className="px-4 py-3 font-medium sr-only">Open</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(page?.results ?? []).map((row) => (
                      <tr key={row.id} className="border-b border-line last:border-0">
                        <td className="px-4 py-3">
                          <div className="font-medium">{row.full_name}</div>
                          <div className="mt-0.5 text-xs text-muted">
                            {row.email} · {row.phone_display || row.phone}
                          </div>
                          {(row.has_cover_letter || row.submission_count > 1) && (
                            <div className="mt-1 flex gap-2 text-[11px] text-muted">
                              {row.has_cover_letter && <span>Cover letter</span>}
                              {row.submission_count > 1 && (
                                <span className="text-warn">
                                  {row.submission_count} submissions
                                </span>
                              )}
                            </div>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <div>{row.job_title}</div>
                          {row.location_label && (
                            <div className="mt-0.5 text-xs text-muted">
                              {row.location_label}
                            </div>
                          )}
                        </td>
                        <td className="px-4 py-3 text-muted">
                          {new Date(row.created_at).toLocaleDateString("en-NG", {
                            day: "numeric",
                            month: "short",
                            year: "numeric",
                          })}
                        </td>
                        <td className="px-4 py-3">
                          <span
                            className={
                              row.status === "new"
                                ? "text-accent"
                                : row.status === "hired"
                                  ? "text-ok"
                                  : row.status === "rejected"
                                    ? "text-muted"
                                    : "text-foreground"
                            }
                          >
                            {row.status_label}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-right">
                          <Link
                            href={`${PATH}/${row.id}`}
                            className="rounded-[var(--radius-card)] border border-line px-3 py-1.5 text-xs hover:border-accent/40"
                          >
                            Open
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <Pagination
              basePath={PATH}
              page={filters.page}
              total={pageCount(page?.count ?? 0)}
              buildQuery={(target) =>
                applicationsQueryString({ ...filters, page: target })
              }
              label="Application pages"
            />
          </>
        )}
      </div>
    </div>
  );
}

/** Real navigations, not a client filter: the list is paginated on the server, so a
 *  browser-side filter would narrow only the page in front of you — which on a list of
 *  people reads as "that candidate is gone". */
function Filters({
  filters,
  stats,
}: {
  filters: ReturnType<typeof parseApplicationFilters>;
  stats: ApplicationStats | null;
}) {
  function href(patch: Partial<typeof filters>): string {
    const query = applicationsQueryString({ ...filters, ...patch, page: 1 });
    return query ? `${PATH}?${query}` : PATH;
  }

  return (
    <div className="mb-4 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Chip href={href({ status: "" })} active={!filters.status}>
          All
        </Chip>
        {APPLICATION_STATUSES.map((option) => (
          <Chip
            key={option.value}
            href={href({ status: option.value })}
            active={filters.status === option.value}
          >
            {option.label}
            {stats?.by_status?.[option.value] ? ` (${stats.by_status[option.value]})` : ""}
          </Chip>
        ))}
        <form action={PATH} className="ml-auto flex gap-2">
          {filters.status && <input type="hidden" name="status" value={filters.status} />}
          {filters.job && <input type="hidden" name="job" value={filters.job} />}
          <input
            name="q"
            defaultValue={filters.q}
            placeholder="Name, email or phone"
            className="rounded-[var(--radius-card)] border border-line bg-surface px-3 py-1.5 text-sm"
          />
          <button
            type="submit"
            className="rounded-[var(--radius-card)] border border-line px-3 py-1.5 text-sm"
          >
            Search
          </button>
        </form>
      </div>

      {stats && stats.by_job.length > 1 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-muted">By role:</span>
          <Chip href={href({ job: "" })} active={!filters.job}>
            Every role
          </Chip>
          {stats.by_job.map((job) => (
            <Chip
              key={job.id}
              href={href({ job: String(job.id) })}
              active={filters.job === String(job.id)}
            >
              {job.title} ({job.application_count})
            </Chip>
          ))}
        </div>
      )}
    </div>
  );
}

function Chip({
  href,
  active,
  children,
}: {
  href: string;
  active: boolean;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      aria-current={active ? "true" : undefined}
      className={[
        "rounded-full border px-3 py-1.5 text-xs",
        active
          ? "border-accent bg-accent text-white"
          : "border-line bg-surface text-muted hover:border-accent/40",
      ].join(" ")}
    >
      {children}
    </Link>
  );
}
