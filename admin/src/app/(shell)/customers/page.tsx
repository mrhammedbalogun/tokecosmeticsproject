import type { Metadata } from "next";
import Link from "next/link";
import { Pagination } from "@/components/Pagination";
import { ApiError } from "@/lib/api";
import {
  customersQueryString,
  parseCustomerFilters,
  sourceLabel,
  type CustomerPage,
} from "@/lib/customers";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";

export const metadata: Metadata = { title: "Customers" };

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

const PATH = "/customers";

/**
 * `/customers` — the customer list, behind `customers.view` (Plan-18b).
 *
 * OPENING THIS PAGE WRITES AN AUDIT ROW, deliberately. `CustomerAdminViewSet` is
 * read-audited: every row is a real person's name, email and phone, and the `search`
 * parameter is the interesting half — "listed every customer matching @gmail.com" is
 * exactly the sentence an audit log exists to be able to write.
 *
 * NO LIFETIME VALUE COLUMN. It is a per-customer aggregate, so a 25-row page would fire 25
 * aggregate queries; it lives on the detail page, and "who spends most" is already
 * answered by the top-customers report in one grouped query.
 */
export default async function CustomersPage({ searchParams }: { searchParams: SearchParams }) {
  await requireAdmin(PATH);

  const raw = new URLSearchParams();
  for (const [key, value] of Object.entries(await searchParams)) {
    if (typeof value === "string") raw.set(key, value);
    else if (Array.isArray(value) && value[0] !== undefined) raw.set(key, value[0]);
  }
  const filters = parseCustomerFilters(raw);
  const qs = customersQueryString(filters);

  let page: CustomerPage | null = null;
  let error: string | null = null;
  try {
    page = await fetchWithAuthOrBounce<CustomerPage>(
      `/admin/customers/${qs ? `?${qs}` : ""}`,
      PATH,
    );
  } catch (e) {
    // `redirect()` throws; rethrown so a merely-stale session is renewed rather than shown
    // an error page.
    if (!(e instanceof ApiError)) throw e;
    error =
      e.status === 403
        ? "Your role does not include access to customers."
        : "The customers could not be loaded.";
  }

  return (
    <div>
      <h1 className="text-lg font-semibold tracking-tight">Customers</h1>
      <p className="mt-1 text-sm text-muted">
        Search by name, email, phone or Toke ID. Opening a customer is recorded in the
        audit log.
      </p>

      <form method="get" className="mt-4 flex flex-wrap items-end gap-3">
        <label className="text-xs text-muted">
          Search
          <input
            type="search"
            name="search"
            defaultValue={filters.search}
            placeholder="name, email, phone, TK-…"
            className="mt-1 block w-64 rounded border border-line bg-surface px-2 py-1.5 text-sm"
          />
        </label>
        <label className="text-xs text-muted">
          Came from
          <select
            name="legacy_source"
            defaultValue={filters.legacy_source}
            className="mt-1 block rounded border border-line bg-surface px-2 py-1.5 text-sm"
          >
            <option value="">Anywhere</option>
            <option value="legacy_ng">Nigeria (current)</option>
            <option value="legacy_ng_old">Nigeria (old store)</option>
            <option value="legacy_intl">International</option>
          </select>
        </label>
        <button
          type="submit"
          className="rounded border border-line px-3 py-1.5 text-sm hover:border-accent"
        >
          Apply
        </button>
      </form>

      {error ? (
        <p className="mt-6 rounded-[var(--radius-card)] border border-warn/40 bg-warn/5 p-4 text-sm">
          {error}
        </p>
      ) : !page || page.results.length === 0 ? (
        <p className="mt-6 rounded-[var(--radius-card)] border border-dashed border-line p-6 text-center text-sm text-muted">
          No customers match.
        </p>
      ) : (
        <>
          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase tracking-wide text-muted">
                <tr>
                  <th className="py-2 pr-4">Customer</th>
                  <th className="py-2 pr-4">Toke ID</th>
                  <th className="py-2 pr-4">Phone</th>
                  <th className="py-2 pr-4">Came from</th>
                  <th className="py-2 pr-4">Joined</th>
                </tr>
              </thead>
              <tbody>
                {page.results.map((row) => (
                  <tr key={row.toke_id} className="border-t border-line align-top">
                    <td className="py-2 pr-4">
                      <Link
                        href={`/customers/${row.toke_id}`}
                        className="font-medium underline underline-offset-2 hover:text-accent"
                      >
                        {row.name || row.email}
                      </Link>
                      <div className="text-xs text-muted">{row.email}</div>
                      {!row.is_active && (
                        <span className="text-xs text-warn">
                          {row.deletion_requested_at ? "deletion requested" : "deactivated"}
                        </span>
                      )}
                    </td>
                    <td className="py-2 pr-4 font-mono text-xs">{row.toke_id}</td>
                    <td className="py-2 pr-4">{row.phone || "—"}</td>
                    <td className="py-2 pr-4 text-xs">{sourceLabel(row.legacy_source)}</td>
                    <td className="py-2 pr-4 text-xs tabular-nums">
                      {row.date_joined.slice(0, 10)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <Pagination
            basePath={PATH}
            page={filters.page}
            total={page.count}
            buildQuery={(p) => customersQueryString(filters, p)}
          />
        </>
      )}
    </div>
  );
}
