/**
 * The audit log's filter bar.
 *
 * A PLAIN GET FORM, and a Server Component. No `"use client"`, no Server Function, no
 * state: submitting navigates to `?actor=…&model=…`, which is exactly the URL shape the
 * page already reads. That makes the filters bookmarkable and shareable, survives a
 * reload, and means the back button undoes a filter — all of which a state-driven
 * version would have to re-implement.
 *
 * `defaultValue` rather than `value`: this is an uncontrolled form, so the browser owns
 * the field contents between renders and the URL owns them across navigations.
 *
 * The `page` parameter is deliberately NOT a hidden field. Changing a filter must return
 * to page 1 — keeping page 7 while narrowing the results is how an operator lands on an
 * empty page and concludes the filter matched nothing.
 */
import type { AuditFilters } from "@/lib/audit";

const FIELD =
  "w-full rounded border border-line bg-surface px-2 py-1.5 text-sm placeholder:text-muted/70 focus:border-accent focus:outline-none";

export function AuditFilterForm({
  filters,
  actions,
}: {
  filters: AuditFilters;
  /** The `action` values seen in the log, to populate the dropdown. */
  actions: string[];
}) {
  return (
    <form
      method="get"
      className="mb-4 grid gap-3 rounded-[var(--radius-card)] border border-line bg-surface p-4 sm:grid-cols-2 lg:grid-cols-6"
    >
      <label className="block text-xs text-muted lg:col-span-2">
        Actor
        <input
          type="text"
          name="actor"
          defaultValue={filters.actor ?? ""}
          placeholder="email contains…"
          className={`mt-1 ${FIELD}`}
        />
      </label>

      <label className="block text-xs text-muted">
        Model
        <input
          type="text"
          name="model"
          defaultValue={filters.model ?? ""}
          placeholder="catalog.product"
          className={`mt-1 ${FIELD}`}
        />
      </label>

      <label className="block text-xs text-muted">
        Action
        <select name="action" defaultValue={filters.action ?? ""} className={`mt-1 ${FIELD}`}>
          <option value="">Any</option>
          {actions.map((action) => (
            <option key={action} value={action}>
              {action}
            </option>
          ))}
        </select>
      </label>

      <label className="block text-xs text-muted">
        After
        {/* `datetime-local` and not `date`: the backend filters on a timestamp, and a
            whole-day granularity is useless when reconstructing an incident. */}
        <input
          type="datetime-local"
          name="after"
          defaultValue={filters.after ?? ""}
          className={`mt-1 ${FIELD}`}
        />
      </label>

      <label className="block text-xs text-muted">
        Before
        <input
          type="datetime-local"
          name="before"
          defaultValue={filters.before ?? ""}
          className={`mt-1 ${FIELD}`}
        />
      </label>

      <div className="flex items-end gap-2 sm:col-span-2 lg:col-span-6">
        <button
          type="submit"
          className="rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90"
        >
          Apply filters
        </button>
        {/* A link, not a reset button: `type="reset"` restores the fields to the values
            the page was rendered with, which for a filtered page is the filter itself. */}
        <a href="/settings/audit" className="text-sm text-muted underline-offset-2 hover:underline">
          Clear
        </a>
      </div>
    </form>
  );
}
