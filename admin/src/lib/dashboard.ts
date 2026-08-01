/** Dashboard arithmetic (Plan-20b). No fetching, no rendering — just the sums and the
 *  geometry, so both can be tested without a browser.
 *
 * THE DASHBOARD COUNTS AND LINKS; IT NEVER RE-DERIVES. Low stock is already defined
 * twice and identically (the digest and the inventory grid both filter
 * `quantity <= threshold`), and needs-attention belongs to the 18a order desk. A third
 * definition here would be the drift those riders warned about, so the widgets call
 * those endpoints and show a count.
 */

/**
 * The order queue's filter for "this needs a decision", as a single constant.
 *
 * `AdminOrderListView` tests for the LITERAL string "true" (`orders/views.py:153`) and its
 * own comment says "there is no needs_review". Sending `needs_review=1` is not an error —
 * it is ignored, the filter never applies, and the caller gets EVERY order back. The
 * dashboard shipped that way for one render and showed "14 orders needing a decision" on a
 * shop with two, which is exactly the kind of number that teaches somebody to distrust the
 * page. One constant, used by both the fetch and the link, so they cannot drift apart.
 */
export const ORDERS_NEEDING_ATTENTION = "needs_attention=true";

export interface RevenueRow {
  currency: string;
  orders: number;
  gross: string;
  refunds: string;
  net: string;
  aov: string;
}

export interface DayRow {
  day: string;
  currency_id: string;
  orders: number;
  gross: string;
}

export interface StatusRow {
  status: string;
  orders: number;
}

/**
 * Percentage change, or `null` when there is nothing to compare against.
 *
 * `null` is the whole point. A previous period of zero has no percentage — dividing gives
 * `Infinity`, and "+∞%" or "NaN%" on a dashboard is how somebody decides the numbers on
 * this page cannot be trusted. The caller renders an em dash.
 */
export function percentDelta(current: number, previous: number): number | null {
  if (!Number.isFinite(current) || !Number.isFinite(previous)) return null;
  if (previous === 0) return null;
  return ((current - previous) / Math.abs(previous)) * 100;
}

export function formatDelta(delta: number | null): string {
  if (delta === null) return "—";
  const rounded = Math.abs(delta) < 0.05 ? 0 : delta;
  return `${rounded > 0 ? "+" : ""}${rounded.toFixed(1)}%`;
}

/** Whether a delta is good news. Refunds going UP is bad, revenue going up is good, so
 *  the caller says which way it reads rather than the formatter guessing. */
export function deltaTone(
  delta: number | null,
  higherIsBetter = true,
): "up" | "down" | "flat" {
  if (delta === null || Math.abs(delta) < 0.05) return "flat";
  const good = higherIsBetter ? delta > 0 : delta < 0;
  return good ? "up" : "down";
}

/** Match a currency's row across two periods; a currency absent from one side is zero
 *  there, never dropped — a market that stopped selling is exactly what a delta is for. */
export function pairByCurrency(
  current: RevenueRow[],
  previous: RevenueRow[],
): { currency: string; current: RevenueRow | null; previous: RevenueRow | null }[] {
  const codes = [...new Set([...current.map((r) => r.currency), ...previous.map((r) => r.currency)])];
  return codes.sort().map((currency) => ({
    currency,
    current: current.find((r) => r.currency === currency) ?? null,
    previous: previous.find((r) => r.currency === currency) ?? null,
  }));
}

export interface Bar {
  day: string;
  value: number;
  /** 0–1, relative to the tallest bar in the series. */
  height: number;
}

/**
 * Bars for one currency's series, with every day in the range present.
 *
 * GAPS ARE FILLED HERE, not by the query: the API returns only days that had orders,
 * because only the caller knows the axis it is drawing. A chart that silently omitted
 * quiet days would compress time and make a bad week look like a busy one.
 */
export function buildBars(rows: DayRow[], start: string, end: string): Bar[] {
  const byDay = new Map<string, number>();
  for (const row of rows) {
    const day = row.day.slice(0, 10);
    byDay.set(day, (byDay.get(day) ?? 0) + Number(row.gross));
  }

  const bars: Bar[] = [];
  const cursor = new Date(`${start}T00:00:00`);
  const last = new Date(`${end}T00:00:00`);
  // Guard against a reversed or absurd range rather than looping forever.
  let guard = 0;
  while (cursor <= last && guard < 400) {
    const key = `${cursor.getFullYear()}-${String(cursor.getMonth() + 1).padStart(2, "0")}-${String(
      cursor.getDate(),
    ).padStart(2, "0")}`;
    bars.push({ day: key, value: byDay.get(key) ?? 0, height: 0 });
    cursor.setDate(cursor.getDate() + 1);
    guard += 1;
  }

  const tallest = Math.max(...bars.map((b) => b.value), 0);
  return bars.map((b) => ({ ...b, height: tallest > 0 ? b.value / tallest : 0 }));
}

/** Statuses in the order somebody thinks about them, so the strip does not reshuffle as
 *  counts change. Anything unrecognised is appended rather than dropped. */
export const STATUS_ORDER = [
  "pending_payment",
  "processing",
  "shipped",
  "delivered",
  "completed",
  "on_hold",
  "expired",
  "cancelled",
  "refunded",
] as const;

export function orderStatuses(rows: StatusRow[]): StatusRow[] {
  const known = STATUS_ORDER.map((status) => rows.find((r) => r.status === status)).filter(
    (r): r is StatusRow => Boolean(r),
  );
  const extra = rows.filter((r) => !(STATUS_ORDER as readonly string[]).includes(r.status));
  return [...known, ...extra];
}

/** The previous window of the same length, immediately before this one — so "vs previous"
 *  compares like with like rather than against a calendar month of a different length. */
export function previousRange(start: string, end: string): { start: string; end: string } {
  const from = new Date(`${start}T00:00:00`);
  const to = new Date(`${end}T00:00:00`);
  const days = Math.round((to.getTime() - from.getTime()) / 86_400_000) + 1;
  const prevEnd = new Date(from);
  prevEnd.setDate(prevEnd.getDate() - 1);
  const prevStart = new Date(prevEnd);
  prevStart.setDate(prevStart.getDate() - (days - 1));
  const iso = (d: Date) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  return { start: iso(prevStart), end: iso(prevEnd) };
}
