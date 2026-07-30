"use client";

/**
 * The audit log as a table. Presentational and client-side only because of the per-row
 * expander; the data arrives already fetched from the Server Component page.
 *
 * THE PRIVACY DESIGN, which is the only non-obvious thing here: the table shows WHICH
 * fields a row recorded, never their values. `changes` holds whatever an admin edit
 * touched — for an order or customer edit that is a name, an address, a phone number —
 * and a table renders every row on screen at once. Names in the row, values behind a
 * deliberate click. Reading the log over somebody's shoulder then shows what moved
 * rather than whose address it was.
 *
 * NO SORTING CONTROLS. The backend orders newest-first and says why; a column header
 * that re-sorted client-side would sort the current PAGE only, which looks like sorting
 * the log and is not.
 */
import { useState } from "react";
import { describeChanges, humanModel, type AuditRow } from "@/lib/audit";

function recordLabel(row: AuditRow): string {
  return `${humanModel(row.model_label)} #${row.object_id}`;
}

function Expander({ row }: { row: AuditRow }) {
  const [open, setOpen] = useState(false);
  const record = recordLabel(row);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        // The record is IN the accessible name: a table of rows all named "Show values"
        // is unusable with a screen reader, and this table is all rows.
        aria-label={`${open ? "Hide" : "Show"} the recorded values for ${record}`}
        className="text-xs text-accent underline-offset-2 hover:underline"
      >
        {open ? "Hide" : "Show"}
      </button>
      {open ? (
        <pre className="mt-2 max-w-full overflow-x-auto rounded bg-shell/5 p-2 text-[11px] leading-relaxed">
          {JSON.stringify(row.changes, null, 2)}
        </pre>
      ) : null}
    </>
  );
}

export function AuditTable({ rows }: { rows: AuditRow[] }) {
  if (rows.length === 0) {
    return (
      <p className="rounded-[var(--radius-card)] border border-line bg-surface p-6 text-sm text-muted">
        No audit entries match these filters.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-[var(--radius-card)] border border-line bg-surface">
      <table className="w-full min-w-[52rem] text-left text-sm">
        <thead className="border-b border-line text-xs uppercase tracking-wide text-muted">
          <tr>
            <th scope="col" className="px-3 py-2 font-medium">When</th>
            <th scope="col" className="px-3 py-2 font-medium">Who</th>
            <th scope="col" className="px-3 py-2 font-medium">Action</th>
            <th scope="col" className="px-3 py-2 font-medium">Record</th>
            <th scope="col" className="px-3 py-2 font-medium">Fields</th>
            <th scope="col" className="px-3 py-2 font-medium">IP</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const hasChanges = Boolean(row.changes && Object.keys(row.changes).length);
            return (
              <tr key={row.id} className="border-b border-line/60 align-top last:border-0">
                <td className="whitespace-nowrap px-3 py-2 text-xs text-muted">
                  {/* The raw ISO string, not a locale format. A server rendering a
                      locale date and a browser hydrating a different one is a hydration
                      mismatch, and an audit timestamp is the last field that should be
                      quietly reformatted. */}
                  <time dateTime={row.created_at}>{row.created_at.replace("T", " ").replace("Z", " UTC")}</time>
                </td>
                <td className="px-3 py-2">{row.actor_email || "—"}</td>
                <td className="whitespace-nowrap px-3 py-2">{row.action}</td>
                <td className="whitespace-nowrap px-3 py-2">{recordLabel(row)}</td>
                <td className="px-3 py-2">
                  <span className="text-xs text-muted">{describeChanges(row.changes)}</span>
                  {hasChanges ? (
                    <div className="mt-1">
                      <Expander row={row} />
                    </div>
                  ) : null}
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-xs text-muted">
                  {row.client_ip ?? "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
