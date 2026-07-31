/**
 * Shapes, filter parsing and pagination arithmetic for the audit viewer. No fetching —
 * that is `app/(shell)/settings/audit/page.tsx`, which is a Server Component and reads
 * through `fetchWithAuthOrBounce`.
 *
 * WHY THE FILTER PARSING IS A PURE FUNCTION HERE rather than inline in the page. The
 * page receives `searchParams` from Next and hands them to the API; everything
 * interesting about that trip — which keys survive, what a blank field means, how a `+`
 * in a timestamp is encoded — is decidable without a request, and a bug in any of it
 * shows up as "the filter silently did nothing". That is the class of bug a test catches
 * cheaply and a person catches late.
 *
 * THE FIVE FILTERS ARE THE BACKEND'S FIVE. `AuditLogListView.get_queryset` reads `actor`,
 * `model`, `after` and `before` by hand and `action`/`model_label`/`object_id` through
 * DjangoFilterBackend. Anything else is ignored server-side, so forwarding it would
 * present an operator with a control that does nothing.
 */

// Moved to `lib/pagination.ts` in Plan-17a Task 2, when the products list became the
// second paged consumer. Re-exported here so every existing import keeps working and
// there is still one implementation of each.
export { PAGE_SIZE, pageCount, pageWindow } from "@/lib/pagination";

export interface AuditRow {
  id: number;
  created_at: string;
  actor: number | null;
  actor_email: string;
  token_jti: string;
  client_ip: string | null;
  model_label: string;
  object_id: string;
  action: string;
  changes: Record<string, unknown> | null;
}

export interface AuditPage {
  count: number;
  next: string | null;
  previous: string | null;
  results: AuditRow[];
}

export interface AuditFilters {
  actor?: string;
  model?: string;
  action?: string;
  object_id?: string;
  after?: string;
  before?: string;
  page: number;
}

/** The filter keys, in the order they appear in the form. `page` is handled separately
 *  because it is pagination rather than a filter. */
export const FILTER_KEYS = ["actor", "model", "action", "object_id", "after", "before"] as const;

export function parseAuditFilters(params: URLSearchParams): AuditFilters {
  const filters: AuditFilters = { page: parsePage(params.get("page")) };
  for (const key of FILTER_KEYS) {
    const value = params.get(key)?.trim();
    // Blank is ABSENT, not empty. An HTML form posts every field it contains, so without
    // this an untouched form sends `?actor=&model=&…` — six filters that each match
    // everything and each cost a query.
    if (value) filters[key] = value;
  }
  return filters;
}

function parsePage(raw: string | null): number {
  // `Number("")` is 0 and `Number(" ")` is 0, so the regex rather than a numeric parse:
  // it rejects "1.5" and "abc" identically and needs no NaN branch.
  if (!raw || !/^\d+$/.test(raw)) return 1;
  const page = Number(raw);
  return page >= 1 ? page : 1;
}

/**
 * The filters as a query string, for both the API call and the pagination links.
 *
 * `URLSearchParams` and never string concatenation: it percent-encodes the `+` in an ISO
 * offset, which a hand-built string does not. An un-encoded `+` arrives at Django as a
 * SPACE and the endpoint answers 400 — it has a written error message about exactly this.
 */
export function auditQueryString(filters: AuditFilters): string {
  const params = new URLSearchParams();
  for (const key of FILTER_KEYS) {
    const value = filters[key];
    if (value) params.set(key, value);
  }
  // Page 1 is the default on both sides, so omitting it keeps the unfiltered URL clean
  // and makes "am I on the first page" answerable by looking at the address bar.
  if (filters.page > 1) params.set("page", String(filters.page));
  return params.toString();
}

/**
 * The one-line summary of a row's `changes` for the table: FIELD NAMES ONLY.
 *
 * The values are deliberately not here. `changes` holds whatever an admin edit touched,
 * which for an order or a customer edit is personal data, and a table renders every row
 * at once. Names in the table, values behind the per-row expander — so reading the log
 * over somebody's shoulder shows what moved, not whose address it was.
 */
export function describeChanges(changes: Record<string, unknown> | null | undefined): string {
  if (!changes) return "—";
  const keys = Object.keys(changes);
  return keys.length ? keys.join(", ") : "—";
}

/** `catalog.product` → `Product`. The API's label is `app_label.modelname`, and the app
 *  half is noise in a column that is already narrow. */
export function humanModel(label: string): string {
  const name = label.includes(".") ? label.split(".")[1] : label;
  return name.charAt(0).toUpperCase() + name.slice(1);
}
