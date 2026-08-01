import type { Metadata } from "next";
import Link from "next/link";
import { ApiError } from "@/lib/api";
import {
  columnsOf,
  defaultRange,
  humanise,
  isReportKey,
  renderCell,
  REPORTS,
  type ReportPayload,
} from "@/lib/reports";
import type { CountryRef } from "@/lib/reference";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";

export const metadata: Metadata = { title: "Reports" };

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

const PATH = "/reports";

/**
 * `/reports` — behind `reports.view`.
 *
 * THE NAV ITEM HAS POINTED HERE SINCE PLAN-16 AND 404'd EVER SINCE, because `reports.view`
 * was granted to Owner and Manager and no endpoint declared it. That is the third scope
 * this project shipped ahead of its surface, after `cms.manage` and `settings.manage`.
 *
 * A PLAIN GET FORM, so a report is a URL: a range somebody is looking at can be sent to
 * someone else, bookmarked, or reloaded. The export link carries the same query string,
 * which is what makes "export what I am looking at" true rather than approximately true.
 */
export default async function ReportsPage({ searchParams }: { searchParams: SearchParams }) {
  await requireAdmin(PATH);

  const params = await searchParams;
  const pick = (key: string): string => {
    const value = params[key];
    if (typeof value === "string") return value;
    if (Array.isArray(value) && typeof value[0] === "string") return value[0];
    return "";
  };

  const fallback = defaultRange();
  const report = isReportKey(pick("report")) ? pick("report") : "revenue";
  const start = pick("start") || fallback.start;
  const end = pick("end") || fallback.end;
  const country = pick("country");

  const query = new URLSearchParams({ start, end });
  if (country) query.set("country", country);
  const qs = query.toString();

  const [dataResult, countriesResult] = await Promise.allSettled([
    fetchWithAuthOrBounce<ReportPayload>(`/admin/reports/${report}/?${qs}`, PATH),
    fetchWithAuthOrBounce<CountryRef[]>("/meta/countries/", PATH),
  ]);

  for (const r of [dataResult, countriesResult]) {
    // `redirect()` throws; rethrown so a merely-stale session is renewed.
    if (r.status === "rejected" && !(r.reason instanceof ApiError)) throw r.reason;
  }

  let error: string | null = null;
  if (dataResult.status === "rejected") {
    const e = dataResult.reason as ApiError;
    error =
      e.status === 403
        ? "Your role does not include reports."
        : ((e.data as { detail?: string } | undefined)?.detail ??
          "That report could not be loaded.");
  }

  const payload = dataResult.status === "fulfilled" ? dataResult.value : null;
  const rows = payload?.rows ?? [];
  const columns = columnsOf(rows);
  const countries =
    countriesResult.status === "fulfilled" && Array.isArray(countriesResult.value)
      ? countriesResult.value
      : [];
  const meta = REPORTS.find((r) => r.key === report);

  return (
    <div>
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Reports</h1>
        <p className="mt-1 text-sm text-muted">
          Totals are shown <strong>per currency and never added together</strong> — an
          exchange rate would put guesswork into the numbers.
        </p>
      </div>

      <form method="get" className="mt-6 grid gap-3 rounded-[var(--radius-card)] border border-line p-4 sm:grid-cols-[1fr_auto_auto_auto_auto]">
        <label className="block text-xs text-muted">
          Report
          <select
            name="report"
            defaultValue={report}
            className="mt-1 w-full rounded border border-line bg-surface px-2 py-1.5 text-sm"
          >
            {REPORTS.map((r) => (
              <option key={r.key} value={r.key}>
                {r.label}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-xs text-muted">
          From
          <input
            type="date"
            name="start"
            defaultValue={start}
            className="mt-1 w-full rounded border border-line bg-surface px-2 py-1.5 text-sm"
          />
        </label>
        <label className="block text-xs text-muted">
          To
          <input
            type="date"
            name="end"
            defaultValue={end}
            className="mt-1 w-full rounded border border-line bg-surface px-2 py-1.5 text-sm"
          />
          <span className="mt-1 block text-xs text-muted">Included.</span>
        </label>
        <label className="block text-xs text-muted">
          Market
          <select
            name="country"
            defaultValue={country}
            className="mt-1 w-full rounded border border-line bg-surface px-2 py-1.5 text-sm"
          >
            <option value="">All markets</option>
            {countries.map((c) => (
              <option key={c.code} value={c.code}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        <div className="flex items-end gap-2">
          <button
            type="submit"
            className="rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90"
          >
            Run
          </button>
          <Link href={PATH} className="py-1.5 text-sm text-muted hover:text-fg">
            Reset
          </Link>
        </div>
      </form>

      {meta && <p className="mt-3 text-sm text-muted">{meta.blurb}</p>}

      <div className="mt-4">
        {error ? (
          <p className="rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-4 text-sm text-warn">
            {error}
          </p>
        ) : rows.length === 0 ? (
          <p className="rounded-[var(--radius-card)] border border-dashed border-line p-6 text-center text-sm text-muted">
            Nothing in this range.
          </p>
        ) : (
          <>
            <div className="mb-2 flex items-center justify-between gap-3">
              <p className="text-xs text-muted">
                {payload?.start} to {payload?.end}
                {payload?.country ? ` · ${payload.country}` : " · all markets"}
              </p>
              {/* Same query string as the table, so the file IS what is on screen.
                  Through the BFF, which attaches the token and read-audits the call. */}
              <a
                href={`/api/admin/reports/${report}/export.csv?${qs}`}
                className="rounded border border-line px-3 py-1.5 text-sm hover:border-accent"
              >
                Export CSV
              </a>
            </div>
            <div className="overflow-x-auto rounded-[var(--radius-card)] border border-line">
              <table className="w-full min-w-[32rem] text-sm">
                <thead className="bg-surface text-xs uppercase tracking-wide text-muted">
                  <tr>
                    {columns.map((c) => (
                      <th key={c} className="px-3 py-2 text-left font-medium">
                        {humanise(c)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, i) => (
                    <tr key={i} className="border-t border-line">
                      {columns.map((c) => (
                        <td key={c} className="px-3 py-2 tabular-nums">
                          {renderCell(row[c])}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {report === "sales_by_category" && (
              <p className="mt-2 text-xs text-muted">
                A product in two categories counts in both, so these rows sum above the
                revenue total. <strong>Unattributed</strong> is revenue whose item has no
                linked variant — migrated international orders, mostly.
              </p>
            )}
            {report === "coupons" && (
              <p className="mt-2 text-xs text-muted">
                Migrated orders carry no redemption rows, so coupon history begins when
                this platform went live.
              </p>
            )}
          </>
        )}
      </div>
    </div>
  );
}
