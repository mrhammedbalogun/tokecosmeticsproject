"use client";

/**
 * The store directory's list and its row actions (Plan-42).
 *
 * ── TWO RENDERINGS, ONE SET OF PARTS ────────────────────────────────────────────────
 *
 * A twelve-column table is the right shape for this data on a desk and the wrong shape
 * on a phone, and `overflow-x-auto` is not a responsive strategy — it is a horizontal
 * scrollbar with good manners. So there are two: a real `<table>` from `lg` up, and
 * stacked cards below it. The pieces that could drift between them (the badges, the
 * place line, the action buttons) are components used by both, so the two renderings
 * can differ in layout and cannot differ in content.
 *
 * ── ARCHIVE ASKS TWICE, EVERYTHING ELSE ASKS ONCE ───────────────────────────────────
 *
 * Show/hide is one click because it is instantly reversible and visible in the same
 * row. Archive takes the row out of the default view, so it is the two-step inline
 * confirm this codebase already uses for deletes — no modal, no page of its own.
 * Nothing here hard-deletes; the backend has no endpoint that would.
 */
import { Fragment, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import {
  archiveStoreAction,
  restoreStoreAction,
  setStoreActiveAction,
  type StoreActionState,
} from "@/app/(shell)/find-stores/actions";
import { StoreForm } from "@/components/stores/StoreForm";
import type { CountryRef } from "@/lib/reference";
import type { RegionRow } from "@/lib/regions";
import type { StoreRow } from "@/lib/stores";

const STATUS_STYLE: Record<string, string> = {
  active: "border-ok/30 bg-ok/10 text-ok",
  inactive: "border-line bg-surface text-muted",
  archived: "border-warn/30 bg-warn/5 text-warn",
};

export function StoreDirectory({
  rows,
  countries,
  regions,
}: {
  rows: StoreRow[];
  countries: CountryRef[];
  regions: RegionRow[];
}) {
  const router = useRouter();
  // `null` = closed, `"new"` = the create form, a number = editing that row.
  const [editing, setEditing] = useState<number | "new" | null>(null);
  const [confirming, setConfirming] = useState<number | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  /** Every row action goes through here so a failure always reaches the operator as a
   *  sentence instead of vanishing into a rejected promise. */
  async function run(action: () => Promise<StoreActionState>) {
    setMessage(null);
    const result = await action();
    if (result.message) setMessage(result.message);
    else if (result.duplicates) {
      setMessage(result.duplicateMessage ?? "That change collides with another store.");
    } else {
      setConfirming(null);
      startTransition(() => router.refresh());
    }
  }

  return (
    <div>
      {/* The match count is the page's, printed above this component — repeating it
          here as "Showing 8 stores" said the same number twice and would have said two
          DIFFERENT numbers the moment the list paginated. */}
      <div className="mb-4 flex items-center justify-end gap-3">
        {editing !== "new" && (
          <button
            type="button"
            onClick={() => setEditing("new")}
            className="rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90"
          >
            Add store
          </button>
        )}
      </div>

      {editing === "new" && (
        <div className="mb-4">
          <StoreForm
            row={null}
            countries={countries}
            regions={regions}
            onDone={() => setEditing(null)}
            onCancel={() => setEditing(null)}
          />
        </div>
      )}

      {message && (
        <p
          role="alert"
          className="mb-4 rounded border border-danger/30 bg-danger/5 p-3 text-sm text-danger"
        >
          {message}
        </p>
      )}

      {rows.length === 0 ? (
        <p className="rounded-[var(--radius-card)] border border-line bg-surface p-6 text-center text-sm text-muted">
          No stores match those filters.
        </p>
      ) : (
        <>
          {/* ── phone and tablet ───────────────────────────────────────────── */}
          <ul className="space-y-3 lg:hidden">
            {rows.map((row) => (
              <li
                key={row.id}
                className="rounded-[var(--radius-card)] border border-line bg-surface p-4"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="font-medium">{row.name}</p>
                    <p className="mt-0.5 text-xs text-muted">{row.store_type_label}</p>
                  </div>
                  <StatusBadge status={row.status} />
                </div>
                <p className="mt-3 text-sm">{row.address}</p>
                <p className="text-xs text-muted">{placeOf(row)}</p>
                <p className="mt-2 text-sm">{row.phone}</p>
                <RowActions
                  row={row}
                  pending={pending}
                  confirming={confirming === row.id}
                  onEdit={() => setEditing(row.id)}
                  onConfirmArchive={() => setConfirming(row.id)}
                  onCancelConfirm={() => setConfirming(null)}
                  onRun={run}
                />
                {editing === row.id && (
                  <div className="mt-3">
                    <StoreForm
                      row={row}
                      countries={countries}
                      regions={regions}
                      onDone={() => setEditing(null)}
                      onCancel={() => setEditing(null)}
                    />
                  </div>
                )}
              </li>
            ))}
          </ul>

          {/* ── desk ───────────────────────────────────────────────────────── */}
          <div className="hidden overflow-hidden rounded-[var(--radius-card)] border border-line lg:block">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="border-b border-line bg-surface text-left text-xs text-muted">
                  <th scope="col" className="p-3 font-medium">Store</th>
                  <th scope="col" className="p-3 font-medium">Type</th>
                  <th scope="col" className="p-3 font-medium">Where</th>
                  <th scope="col" className="p-3 font-medium">Phone</th>
                  <th scope="col" className="p-3 font-medium">Status</th>
                  <th scope="col" className="p-3 font-medium">Updated</th>
                  <th scope="col" className="p-3 font-medium">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  // A keyed Fragment per row: the edit form is a second `<tr>` under
                  // the first, which keeps it in the table's flow instead of floating
                  // in a modal over the list the operator is comparing it against. A
                  // wrapper `<div>` is not valid inside `<tbody>`.
                  <Fragment key={row.id}>
                    <tr className="border-b border-line align-top last:border-0">
                      <td className="p-3">
                        <p className="font-medium">{row.name}</p>
                        <p className="text-xs text-muted">{row.address}</p>
                      </td>
                      <td className="p-3">{row.store_type_label}</td>
                      <td className="p-3 text-xs">{placeOf(row)}</td>
                      <td className="p-3 whitespace-nowrap">
                        {row.phone}
                        {row.phone_alt && (
                          <span className="block text-xs text-muted">{row.phone_alt}</span>
                        )}
                      </td>
                      <td className="p-3">
                        <StatusBadge status={row.status} />
                      </td>
                      <td className="p-3 whitespace-nowrap text-xs text-muted">
                        <span title={`Added ${formatDate(row.created_at)}`}>
                          {formatDate(row.updated_at)}
                        </span>
                      </td>
                      <td className="p-3">
                        <RowActions
                          row={row}
                          pending={pending}
                          confirming={confirming === row.id}
                          onEdit={() => setEditing(editing === row.id ? null : row.id)}
                          onConfirmArchive={() => setConfirming(row.id)}
                          onCancelConfirm={() => setConfirming(null)}
                          onRun={run}
                        />
                      </td>
                    </tr>
                    {editing === row.id && (
                      <tr className="border-b border-line last:border-0">
                        <td colSpan={7} className="bg-background/60 p-3">
                          <StoreForm
                            row={row}
                            countries={countries}
                            regions={regions}
                            onDone={() => setEditing(null)}
                            onCancel={() => setEditing(null)}
                          />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

function RowActions({
  row,
  pending,
  confirming,
  onEdit,
  onConfirmArchive,
  onCancelConfirm,
  onRun,
}: {
  row: StoreRow;
  pending: boolean;
  confirming: boolean;
  onEdit: () => void;
  onConfirmArchive: () => void;
  onCancelConfirm: () => void;
  onRun: (action: () => Promise<StoreActionState>) => Promise<void>;
}) {
  const archived = row.status === "archived";
  const button =
    "rounded border border-line px-2 py-1 text-xs hover:border-accent disabled:opacity-60";

  if (archived) {
    return (
      <div className="mt-3 flex flex-wrap gap-2 lg:mt-0">
        <button
          type="button"
          disabled={pending}
          onClick={() => void onRun(() => restoreStoreAction(row.id))}
          className={button}
        >
          Restore
        </button>
        {/* Said out loud because it surprises people: restoring does not put the shop
            back on the website, it puts it back in the directory, hidden. */}
        <span className="self-center text-xs text-muted">comes back hidden</span>
      </div>
    );
  }

  return (
    <div className="mt-3 flex flex-wrap gap-2 lg:mt-0">
      <button type="button" onClick={onEdit} className={button}>
        Edit
      </button>
      <button
        type="button"
        disabled={pending}
        onClick={() => void onRun(() => setStoreActiveAction(row.id, !row.is_active))}
        className={button}
      >
        {row.is_active ? "Hide from site" : "Show on site"}
      </button>
      {confirming ? (
        <>
          <button
            type="button"
            disabled={pending}
            onClick={() => void onRun(() => archiveStoreAction(row.id))}
            className="rounded border border-danger px-2 py-1 text-xs text-danger hover:bg-danger/10 disabled:opacity-60"
          >
            Archive it
          </button>
          <button type="button" onClick={onCancelConfirm} className={button}>
            Keep
          </button>
        </>
      ) : (
        <button
          type="button"
          onClick={onConfirmArchive}
          className="rounded border border-line px-2 py-1 text-xs text-danger hover:border-danger"
        >
          Archive
        </button>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: StoreRow["status"] }) {
  return (
    <span
      className={`inline-block whitespace-nowrap rounded-full border px-2 py-0.5 text-xs capitalize ${
        STATUS_STYLE[status] ?? STATUS_STYLE.inactive
      }`}
    >
      {status}
    </span>
  );
}

/** "Alimosho · Lagos · Nigeria" — the LGA where there is one, the free-text city where
 *  the state has no districts. */
function placeOf(row: StoreRow): string {
  return [row.area_name || row.city_text, row.state_name, row.country_name]
    .filter(Boolean)
    .join(" · ");
}

function formatDate(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? "—"
    : date.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}
