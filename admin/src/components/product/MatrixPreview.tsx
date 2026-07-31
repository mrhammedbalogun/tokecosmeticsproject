"use client";

/**
 * What Generate would do, before it does it — and then Apply.
 *
 * Three groups, always in this order: what will be created, what already exists, and what
 * falls outside the matrix. The third is the one that needs explaining, so it explains
 * itself rather than being a bare list.
 *
 * ── ADDING AN AXIS ORPHANS EVERYTHING, AND THIS IS WHERE THAT LANDS ─────────────────
 *
 * `diffMatrix` matches on the exact key set, so a variant with `{Size: 100ml}` does not
 * match `{Size: 100ml, Shade: Fair}` — it has no value for the new axis, and guessing one
 * would invent data. The arithmetic is right, but the effect is startling: add an axis to a
 * product with four variants and all four become orphans while four new combinations want
 * creating. Apply never deletes, so the danger is not loss — it is ending up with eight
 * variants where four were meant. Hence the warning, shown only in that exact situation.
 *
 * PRESENTATIONAL: the preview, the SKU drafts and the per-row results live in
 * `ProductEditor`, because this panel unmounts on every tab switch.
 */
import type { Combination, MatrixDiff } from "@/lib/variant-matrix";

const GHOST =
  "rounded border border-line px-2 py-1 text-xs text-muted hover:border-accent hover:text-fg disabled:opacity-40";

export type RowStatus = "pending" | "creating" | "created" | "failed";

export interface RowState {
  sku: string;
  name: string;
  status: RowStatus;
  error?: string;
}

export const combinationKey = (combination: Combination) =>
  Object.entries(combination)
    .map(([k, v]) => `${k}=${v}`)
    .sort()
    .join("|");

export function MatrixPreview({
  diff,
  rows,
  busy,
  stale,
  onSku,
  onApply,
  onRegenerate,
}: {
  diff: MatrixDiff;
  /** Keyed by `combinationKey`. */
  rows: Record<string, RowState>;
  busy: boolean;
  /** True when the axes changed after this preview was generated. */
  stale: boolean;
  onSku: (key: string, sku: string) => void;
  onApply: () => void;
  onRegenerate: () => void;
}) {
  const outstanding = diff.missing.filter((c) => {
    const row = rows[combinationKey(c)];
    return !row || row.status !== "created";
  });
  const createdCount = diff.missing.length - outstanding.length;
  // The exact situation the warning is for: everything the product had is now outside the
  // matrix, and everything the matrix wants is new.
  const everythingOrphaned = diff.existing.length === 0 && diff.orphaned.length > 0;

  return (
    <div className="rounded-[var(--radius-card)] border border-line p-4">
      <div className="flex items-start justify-between gap-4">
        <h2 className="text-sm font-medium">Generated matrix</h2>
        {stale && (
          <button type="button" onClick={onRegenerate} className={GHOST}>
            Options changed — generate again
          </button>
        )}
      </div>

      {everythingOrphaned && (
        <p className="mt-3 rounded border border-warn/30 bg-warn/5 p-3 text-sm text-warn">
          <strong>None of the existing variants fit this matrix.</strong> That happens when
          an option is added — the variants you already have carry no value for it. Applying
          would leave you with {diff.orphaned.length + diff.missing.length} variants where
          you probably want {diff.missing.length}. Nothing is deleted either way.
        </p>
      )}

      {/* --- will be created ---------------------------------------------------------- */}
      <section className="mt-4">
        <h3 className="text-xs font-medium text-muted">
          {diff.missing.length === 0
            ? "Nothing new to create"
            : `${diff.missing.length} to create`}
          {createdCount > 0 && ` · ${createdCount} done`}
        </h3>

        {diff.missing.length > 0 && (
          <ul className="mt-2 space-y-2">
            {diff.missing.map((combination) => {
              const key = combinationKey(combination);
              const row = rows[key];
              if (!row) return null;
              return (
                <li key={key} className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="min-w-44 flex-1">{row.name}</span>
                  <input
                    type="text"
                    value={row.sku}
                    onChange={(e) => onSku(key, e.target.value)}
                    disabled={row.status === "created" || busy}
                    aria-label={`SKU for ${row.name}`}
                    className={`w-64 rounded border bg-surface px-2 py-1 font-mono text-xs focus:outline-none ${
                      row.status === "failed" ? "border-warn" : "border-line focus:border-accent"
                    }`}
                  />
                  <span className="w-20 text-xs">
                    {row.status === "created" && <span className="text-ok">Created</span>}
                    {row.status === "creating" && <span className="text-muted">Creating…</span>}
                    {row.status === "failed" && <span className="text-warn">Failed</span>}
                  </span>
                  {row.error && (
                    <span className="w-full text-xs text-warn sm:w-auto">{row.error}</span>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {/* --- already exists ------------------------------------------------------------ */}
      {diff.existing.length > 0 && (
        <section className="mt-5">
          <h3 className="text-xs font-medium text-muted">
            {diff.existing.length} already exist
          </h3>
          <ul className="mt-2 flex flex-wrap gap-2">
            {diff.existing.map(({ variant }) => (
              <li
                key={variant.id}
                className="rounded-full border border-line bg-surface px-3 py-1 text-xs"
              >
                {variant.name}{" "}
                <span className="font-mono text-muted">{variant.sku}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* --- orphans -------------------------------------------------------------------- */}
      {diff.orphaned.length > 0 && (
        <section className="mt-5">
          <h3 className="text-xs font-medium text-muted">
            {diff.orphaned.length} outside this matrix
          </h3>
          <p className="mt-1 text-xs text-muted">
            {/* Said plainly, because "orphaned" reads like something is about to happen to
                them. Nothing is: deleting a variant would take its prices, its stock and
                its links from past orders with it. */}
            Left exactly as they are. Deleting a variant would take its prices, its stock and
            its place in past orders with it, so the builder never does.
          </p>
          <ul className="mt-2 flex flex-wrap gap-2">
            {diff.orphaned.map((variant) => (
              <li
                key={variant.id}
                className="rounded-full border border-warn/30 bg-warn/5 px-3 py-1 text-xs"
              >
                {variant.name} <span className="font-mono text-muted">{variant.sku}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="mt-5 flex items-center gap-3">
        <button
          type="button"
          onClick={onApply}
          disabled={busy || stale || outstanding.length === 0}
          className="rounded bg-accent px-4 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-40"
        >
          {busy
            ? "Creating…"
            : outstanding.length === 0
              ? "Nothing to apply"
              : `Create ${outstanding.length} ${outstanding.length === 1 ? "variant" : "variants"}`}
        </button>
        {stale && (
          <span className="text-xs text-warn">
            The options changed since this was generated.
          </span>
        )}
      </div>
    </div>
  );
}
