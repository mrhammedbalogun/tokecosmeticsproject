/** Report shapes and the vocabulary the endpoint reads (Plan-20a).
 *
 * THE REPORT LIST IS THE BACKEND'S. `analytics/views.REPORTS` decides what exists; this
 * mirrors it for the picker. A name here that the API does not serve is a 404 the operator
 * cannot explain, so the two are kept deliberately short and in step.
 */
export const REPORTS = [
  {
    key: "revenue",
    label: "Revenue",
    blurb: "Gross, refunds and net per currency, with order count and average order value.",
    namesCustomers: false,
  },
  {
    key: "orders_by_status",
    label: "Orders by status",
    blurb: "Every status, including the orders that never paid.",
    namesCustomers: false,
  },
  {
    key: "top_products",
    label: "Top products",
    blurb: "By revenue. Grouped on the order's own snapshot, so migrated items are included.",
    namesCustomers: false,
  },
  {
    key: "sales_by_category",
    label: "Sales by category",
    blurb:
      "Revenue per category, plus an Unattributed row for items with no linked variant.",
    namesCustomers: false,
  },
  {
    key: "top_customers",
    label: "Top customers",
    blurb: "Lifetime value in the range, per currency. Exporting this needs orders.manage.",
    namesCustomers: true,
  },
  {
    key: "coupons",
    label: "Coupon performance",
    blurb: "Redemptions and the discount given away. Migrated orders carry no redemptions.",
    namesCustomers: false,
  },
] as const;

export type ReportKey = (typeof REPORTS)[number]["key"];

export function isReportKey(value: string): value is ReportKey {
  return REPORTS.some((r) => r.key === value);
}

export interface ReportPayload {
  report: string;
  start: string;
  end: string;
  country: string;
  rows: Record<string, unknown>[];
}

/** `YYYY-MM-DD` for an input[type=date], in local time. */
export function isoDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate(),
  ).padStart(2, "0")}`;
}

/** The default window: the last 30 days, matching the backend's own default so an
 *  unparameterised page and an unparameterised request agree. */
export function defaultRange(today = new Date()): { start: string; end: string } {
  const start = new Date(today);
  start.setDate(start.getDate() - 29);
  return { start: isoDate(start), end: isoDate(today) };
}

/** Column headers derived from the rows themselves, so a report's columns are its
 *  query's columns and the two cannot drift. Keys are humanised for display only. */
export function columnsOf(rows: Record<string, unknown>[]): string[] {
  return rows.length ? Object.keys(rows[0]) : [];
}

export function humanise(key: string): string {
  return key
    .replace(/_id$/, "")
    .replace(/_/g, " ")
    .replace(/^./, (c) => c.toUpperCase());
}

/** Cells the reports produce are strings, numbers, or null for the unattributed bucket. */
export function renderCell(value: unknown): string {
  if (value === null || value === undefined || value === "") return "Unattributed";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
