import type { Metadata } from "next";
import Link from "next/link";
import {
  AttentionWidgets,
  KpiCards,
  RevenueChart,
  StatusStrip,
} from "@/components/dashboard/DashboardPanels";
import { getAdminMeOrNull } from "@/lib/admin-me";
import { previousRange, type DayRow, type RevenueRow, type StatusRow } from "@/lib/dashboard";
import { visibleNav } from "@/lib/nav";
import { ORDERS_NEEDING_ATTENTION } from "@/lib/dashboard";
import { defaultRange } from "@/lib/reports";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";

export const metadata: Metadata = { title: "Dashboard" };

const PATH = "/";

/**
 * The dashboard (Plan-20b).
 *
 * ── IT MUST DEGRADE, NOT 403 ────────────────────────────────────────────────────────
 *
 * `nav.ts` gives this page `scopes: []`, so EVERY staff member lands here — including
 * Support, who holds neither `reports.view` nor `products.manage`. So each panel is
 * fetched independently with `allSettled` and simply omitted when its call is refused.
 * A wall of error boxes on the first screen after signing in would read as a broken
 * admin rather than as a permission boundary working correctly.
 *
 * ── IT COUNTS AND LINKS ─────────────────────────────────────────────────────────────
 *
 * Low stock belongs to 17c's inventory grid and needs-attention to 18a's order desk.
 * Those endpoints are called for their counts; the predicates are not reimplemented here.
 *
 * `fetchWithAuthOrBounce`, never `fetchWithAuth`: a Server Component cannot persist a
 * rotated refresh token.
 */
export default async function DashboardPage() {
  await requireAdmin(PATH);
  const me = await getAdminMeOrNull();

  const { start, end } = defaultRange();
  const prev = previousRange(start, end);
  const range = `start=${start}&end=${end}`;

  const [revenue, previousRevenue, byDay, byStatus, needsReview, lowStock, awaiting] =
    await Promise.allSettled([
      fetchWithAuthOrBounce<{ rows: RevenueRow[] }>(`/admin/reports/revenue/?${range}`, PATH),
      fetchWithAuthOrBounce<{ rows: RevenueRow[] }>(
        `/admin/reports/revenue/?start=${prev.start}&end=${prev.end}`,
        PATH,
      ),
      fetchWithAuthOrBounce<{ rows: DayRow[] }>(`/admin/reports/revenue_by_day/?${range}`, PATH),
      fetchWithAuthOrBounce<{ rows: StatusRow[] }>(`/admin/reports/orders_by_status/?${range}`, PATH),
      // `needs_attention=true` — the LITERAL string, which is what
      // `AdminOrderListView` tests for. `needs_review=1` is silently ignored and returns
      // every order, which is how this card first rendered "14 orders needing a decision"
      // on a shop with two. A count nobody can act on is worse than no card.
      fetchWithAuthOrBounce<{ count: number }>(
        `/admin/orders/?${ORDERS_NEEDING_ATTENTION}`,
        PATH,
      ),
      fetchWithAuthOrBounce<{ count: number }>("/admin/stock/grid/?low_stock=1", PATH),
      fetchWithAuthOrBounce<{ count: number }>(
        "/admin/orders/?status=pending_payment&page_size=1",
        PATH,
      ),
    ]);

  const rowsOf = <T,>(r: PromiseSettledResult<{ rows: T[] }>): T[] =>
    r.status === "fulfilled" ? (r.value?.rows ?? []) : [];
  const countOf = (r: PromiseSettledResult<{ count: number }>): number | null =>
    r.status === "fulfilled" ? (r.value?.count ?? 0) : null;

  const canSeeReports = revenue.status === "fulfilled";
  const sections = visibleNav(me?.scopes).filter((item) => item.href !== "/");

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">
          {me?.name ? `Hello, ${me.name.split(" ")[0]}` : "Dashboard"}
        </h1>
        <p className="mt-1 text-sm text-muted">
          {start} to {end}
          {me?.groups?.length ? ` · ${me.groups.join(", ")}` : ""}
        </p>
      </div>

      <AttentionWidgets
        needsReview={countOf(needsReview)}
        lowStock={countOf(lowStock)}
        expiring={countOf(awaiting)}
      />

      {canSeeReports ? (
        <>
          <KpiCards current={rowsOf(revenue)} previous={rowsOf(previousRevenue)} />
          <RevenueChart rows={rowsOf(byDay)} start={start} end={end} />
          <StatusStrip rows={rowsOf(byStatus)} />
          <p className="text-sm">
            <Link href="/reports" className="underline underline-offset-2 hover:text-accent">
              All reports and exports →
            </Link>
          </p>
        </>
      ) : (
        // Not an error: Support legitimately lands here without `reports.view`.
        <p className="rounded-[var(--radius-card)] border border-dashed border-line p-6 text-sm text-muted">
          Sales figures are not part of your role. The queues above are.
        </p>
      )}

      <section>
        <h2 className="mb-2 text-sm font-semibold">Everything else</h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {sections.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="rounded-[var(--radius-card)] border border-line bg-surface p-4 transition-colors hover:border-accent"
            >
              <p className="text-sm font-semibold">{item.label}</p>
            </Link>
          ))}
        </div>
      </section>
    </div>
  );
}
