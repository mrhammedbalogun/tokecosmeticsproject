import type { Metadata } from "next";
import Link from "next/link";
import { IntakeSwitch } from "@/components/entrepreneurship/IntakeSwitch";
import { Pagination } from "@/components/Pagination";
import { ApiError } from "@/lib/api";
import { getAdminMeOrNull } from "@/lib/admin-me";
import {
  APPLICATION_STATUSES,
  applicationsQueryString,
  parseApplicationFilters,
  type ApplicationRow,
  type ApplicationStats,
  type Page,
  type ProgrammeSettings,
} from "@/lib/entrepreneurship";
import { pageCount } from "@/lib/pagination";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";

export const metadata: Metadata = { title: "Student Program" };

const PATH = "/entrepreneurship";

/**
 * `/entrepreneurship` — the students who applied, and the switch that decides whether
 * more can.
 *
 * THE PAGE IS NOT THE AUTHORIZATION. `requireAdmin` establishes a session and nothing
 * more; whether this person may read applications is decided by `HasAdminScope` on every
 * endpoint, on every request, from the database. Somebody without the scope gets a
 * session, a page, and a sentence saying so.
 *
 * ── THIS SCREEN'S READS ARE AUDITED, AND THAT IS DELIBERATE ─────────────────────────
 *
 * Every row is a named student's email, phone number and school. The backend sets
 * `audit_reads = True` on the viewset and `apps/core/tests/test_audit_guard.py` enforces
 * it by matching the scope prefix — so opening this list leaves a row saying who did.
 *
 * ── TWO SCOPES, ONE DOOR ────────────────────────────────────────────────────────────
 *
 * The nav item opens for a holder of EITHER `entrepreneurship.manage` or
 * `entrepreneurship.applications.manage`, so this page copes with a visitor holding only
 * the first: they get the intake switch and are told the applications are not theirs,
 * rather than an empty table that looks broken.
 */
type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export default async function ProgrammePage({
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

  const me = await getAdminMeOrNull();
  const scopes = new Set(me?.scopes ?? []);
  const canSeeApplications = scopes.has("entrepreneurship.applications.manage");
  const canManageIntake = scopes.has("entrepreneurship.manage");

  let page: Page<ApplicationRow> | null = null;
  let stats: ApplicationStats | null = null;
  let settings: ProgrammeSettings | null = null;
  let error: string | null = null;

  try {
    const query = applicationsQueryString(filters);
    const [rows, counts, config] = await Promise.all([
      canSeeApplications
        ? fetchWithAuthOrBounce<Page<ApplicationRow>>(
            `/admin/entrepreneurship/applications/${query ? `?${query}` : ""}`,
            PATH,
          )
        : Promise.resolve(null),
      // The counts degrade rather than failing the page — losing the chips costs a
      // filter, throwing costs the applications.
      canSeeApplications
        ? fetchWithAuthOrBounce<ApplicationStats>(
            "/admin/entrepreneurship/applications/stats/",
            PATH,
          ).catch(() => null)
        : Promise.resolve(null),
      canManageIntake
        ? fetchWithAuthOrBounce<ProgrammeSettings>(
            "/admin/entrepreneurship/settings/",
            PATH,
          ).catch(() => null)
        : Promise.resolve(null),
    ]);
    page = rows;
    stats = counts;
    settings = config;
  } catch (e) {
    // `redirect()` works by THROWING, so a bare catch-all here would swallow the
    // renewal bounce and show an error page to somebody whose session was merely stale.
    if (!(e instanceof ApiError)) throw e;
    error =
      e.status === 403
        ? "Your role does not include reading programme applications."
        : "The applications could not be loaded.";
  }

  return (
    <div>
      <h1 className="text-lg font-semibold tracking-tight">Student Program</h1>
      <p className="mt-1 text-sm text-muted">
        Students who applied through{" "}
        <span className="font-medium">
          tokecosmetics.com/entrepreneurial-program
        </span>
        . They receive stock up front and pay for it as they sell, so a working phone
        number matters more here than anywhere else on this admin.
      </p>

      <Tabs
        active="applications"
        canSeeNotifications={scopes.has("entrepreneurship.notifications.manage")}
      />

      {canManageIntake && settings && (
        <div className="mt-6">
          <IntakeSwitch settings={settings} />
        </div>
      )}

      <div className="mt-6">
        {!canSeeApplications ? (
          <p className="rounded-[var(--radius-card)] border border-line bg-surface p-4 text-sm text-muted">
            Your role does not include reading programme applications. The intake switch
            above is yours; the students who applied are not.
          </p>
        ) : error ? (
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
                {filters.status || filters.country || filters.q
                  ? "Nothing matches those filters."
                  : "No applications yet. They appear here the moment a student applies."}
              </p>
            ) : (
              <div className="overflow-x-auto rounded-[var(--radius-card)] border border-line bg-surface">
                <table className="w-full min-w-[820px] text-sm">
                  <thead className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
                    <tr>
                      <th className="px-4 py-3 font-medium">Student</th>
                      <th className="px-4 py-3 font-medium">Studying</th>
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
                          {(row.has_motivation ||
                            row.social_handle ||
                            row.submission_count > 1) && (
                            <div className="mt-1 flex flex-wrap gap-2 text-[11px] text-muted">
                              {row.social_handle && <span>{row.social_handle}</span>}
                              {row.has_motivation && <span>Wrote a note</span>}
                              {row.submission_count > 1 && (
                                <span className="text-warn">
                                  {row.submission_count} submissions
                                </span>
                              )}
                            </div>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <div>{row.institution}</div>
                          <div className="mt-0.5 text-xs text-muted">
                            {row.course_of_study}
                            {row.academic_level && ` · ${row.academic_level}`}
                            {row.country_name && ` · ${row.country_name}`}
                          </div>
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
                                : row.status === "approved"
                                  ? "text-ok"
                                  : row.status === "rejected" ||
                                      row.status === "withdrawn"
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

export function Tabs({
  active,
  canSeeNotifications = false,
}: {
  active: "applications" | "notifications";
  canSeeNotifications?: boolean;
}) {
  // The Notifications tab is gated on its OWN scope, because the two are separate
  // grants. Hiding a tab is ergonomics, never authorization — every endpoint behind
  // them re-checks on each request, from the database.
  const tabs = [
    { key: "applications", label: "Applications", href: PATH },
    ...(canSeeNotifications
      ? [
          {
            key: "notifications",
            label: "Notifications",
            href: `${PATH}/notifications`,
          },
        ]
      : []),
  ];
  return (
    <nav
      className="mt-5 flex gap-1 border-b border-line"
      aria-label="Student Program sections"
    >
      {tabs.map((tab) => (
        <Link
          key={tab.key}
          href={tab.href}
          aria-current={active === tab.key ? "page" : undefined}
          className={[
            "-mb-px border-b-2 px-4 py-2 text-sm",
            active === tab.key
              ? "border-accent font-medium text-accent"
              : "border-transparent text-muted hover:text-foreground",
          ].join(" ")}
        >
          {tab.label}
        </Link>
      ))}
    </nav>
  );
}

/** Real navigations, not a client filter: the list is paginated on the server, so a
 *  browser-side filter would narrow only the page in front of you — which on a list of
 *  people reads as "that student is gone". */
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
            {stats?.by_status?.[option.value]
              ? ` (${stats.by_status[option.value]})`
              : ""}
          </Chip>
        ))}
        <form action={PATH} className="ml-auto flex gap-2">
          {filters.status && (
            <input type="hidden" name="status" value={filters.status} />
          )}
          {filters.country && (
            <input type="hidden" name="country" value={filters.country} />
          )}
          <input
            name="q"
            defaultValue={filters.q}
            placeholder="Name, email, phone or school"
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

      {stats && stats.by_country.length > 1 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-muted">By country:</span>
          <Chip href={href({ country: "" })} active={!filters.country}>
            Everywhere
          </Chip>
          {stats.by_country.map((row) => (
            <Chip
              key={row.country_id}
              href={href({ country: row.country_id })}
              active={filters.country === row.country_id}
            >
              {row.country__name} ({row.count})
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
