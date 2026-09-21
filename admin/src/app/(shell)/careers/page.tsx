import type { Metadata } from "next";
import Link from "next/link";
import { JobTable } from "@/components/careers/JobTable";
import { Pagination } from "@/components/Pagination";
import { ApiError } from "@/lib/api";
import { getAdminMeOrNull } from "@/lib/admin-me";
import { jobsQueryString, parseJobFilters, type JobRow, type Page } from "@/lib/careers";
import { pageCount } from "@/lib/pagination";
import type { CountryRef } from "@/lib/reference";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";

export const metadata: Metadata = { title: "Careers" };

const PATH = "/careers";

/**
 * `/careers` — the roles board behind tokecosmetics.com/careers, scoped `careers.manage`.
 *
 * THE PAGE IS NOT THE AUTHORIZATION. `requireAdmin` establishes a session and nothing
 * more; whether this person may manage roles is decided by `HasAdminScope` on every
 * endpoint, on every request, from the database. Somebody without the scope gets a
 * session, a page, and a sentence saying so.
 *
 * ── TWO SCOPES, ONE DOOR ────────────────────────────────────────────────────────────
 *
 * The nav item opens for a holder of EITHER `careers.manage` or
 * `careers.applications.manage`, so this page has to cope with a visitor who holds only
 * the second: it shows them the tab bar and the applications link, and tells them the
 * roles list is not theirs, rather than rendering an empty table that looks broken.
 */
type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export default async function CareersPage({ searchParams }: { searchParams: SearchParams }) {
  await requireAdmin(PATH);

  const raw = new URLSearchParams();
  for (const [key, value] of Object.entries(await searchParams)) {
    if (typeof value === "string") raw.set(key, value);
    else if (Array.isArray(value) && value[0] !== undefined) raw.set(key, value[0]);
  }
  const filters = parseJobFilters(raw);

  const me = await getAdminMeOrNull();
  const scopes = new Set(me?.scopes ?? []);

  let page: Page<JobRow> | null = null;
  let countries: CountryRef[] = [];
  let error: string | null = null;
  try {
    const query = jobsQueryString(filters);
    const [jobs, countryList] = await Promise.all([
      fetchWithAuthOrBounce<Page<JobRow>>(
        `/admin/careers/jobs/${query ? `?${query}` : ""}`,
        PATH,
      ),
      // Reference data degrades rather than failing the page: a missing country list
      // costs the operator a dropdown, a thrown one costs them the board.
      fetchWithAuthOrBounce<CountryRef[]>("/meta/countries/", PATH).catch(() => []),
    ]);
    page = jobs;
    countries = (Array.isArray(countryList) ? countryList : [])
      // "ZZ / International" is a pricing bucket, not a place anybody is hired into.
      .filter((c) => !c.is_rest_of_world)
      .sort((a, b) => a.name.localeCompare(b.name));
  } catch (e) {
    // `redirect()` works by THROWING, so a bare catch-all here would swallow the renewal
    // bounce and show an error page to somebody whose session was merely stale.
    if (!(e instanceof ApiError)) throw e;
    error =
      e.status === 403
        ? "Your role does not include managing job roles."
        : "The careers board could not be loaded.";
  }

  return (
    <div>
      <h1 className="text-lg font-semibold tracking-tight">Careers</h1>
      <p className="mt-1 text-sm text-muted">
        The roles on <span className="font-medium">tokecosmetics.com/careers</span>, and
        the people who applied to them. Open roles show on the website; drafts and
        archived ones stay here.
      </p>

      <Tabs active="roles" canSeeApplications={scopes.has("careers.applications.manage")} />

      <div className="mt-6">
        {error ? (
          <p className="rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-4 text-sm text-warn">
            {error}
          </p>
        ) : (
          <>
            <StatusFilter active={filters.status} q={filters.q} />
            <p className="mb-2 text-xs text-muted">
              {page?.count ?? 0} {page?.count === 1 ? "role" : "roles"}.
            </p>
            <JobTable
              rows={page?.results ?? []}
              countries={countries}
              canSeeApplications={scopes.has("careers.applications.manage")}
            />
            <Pagination
              basePath={PATH}
              page={filters.page}
              total={pageCount(page?.count ?? 0)}
              buildQuery={(target) => jobsQueryString({ ...filters, page: target })}
              label="Role pages"
            />
          </>
        )}
      </div>
    </div>
  );
}

export function Tabs({
  active,
  canSeeApplications,
}: {
  active: "roles" | "applications";
  canSeeApplications: boolean;
}) {
  const tabs = [
    { key: "roles", label: "Roles", href: "/careers" },
    ...(canSeeApplications
      ? [{ key: "applications", label: "Applications", href: "/careers/applications" }]
      : []),
  ];
  return (
    <nav className="mt-5 flex gap-1 border-b border-line" aria-label="Careers sections">
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

/** Server-rendered links rather than a client filter: the list is paginated on the
 *  server, so the filter has to be a real navigation or it would narrow only the page
 *  in front of you. */
function StatusFilter({ active, q }: { active: string; q: string }) {
  const options = [
    { value: "", label: "Live board" },
    { value: "draft", label: "Drafts" },
    { value: "open", label: "Open" },
    { value: "closed", label: "Closed" },
    { value: "archived", label: "Archived" },
    { value: "all", label: "Everything" },
  ];
  return (
    <div className="mb-4 flex flex-wrap items-center gap-2">
      {options.map((option) => {
        const query = new URLSearchParams();
        if (option.value) query.set("status", option.value);
        if (q) query.set("q", q);
        const href = query.toString() ? `/careers?${query}` : "/careers";
        const current = active === option.value;
        return (
          <Link
            key={option.value || "default"}
            href={href}
            aria-current={current ? "true" : undefined}
            className={[
              "rounded-full border px-3 py-1.5 text-xs",
              current
                ? "border-accent bg-accent text-white"
                : "border-line bg-surface text-muted hover:border-accent/40",
            ].join(" ")}
          >
            {option.label}
          </Link>
        );
      })}
      <form action="/careers" className="ml-auto flex gap-2">
        {active && <input type="hidden" name="status" value={active} />}
        <input
          name="q"
          defaultValue={q}
          placeholder="Search roles"
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
  );
}
