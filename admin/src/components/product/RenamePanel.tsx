"use client";

/**
 * The two bulk writes over a product's existing variants: renaming an option, and fixing
 * variant names that do not match their options.
 *
 * ── BOTH ARE BULK WRITES, AND ARE CONFIRMED WITH A COUNT ────────────────────────────
 *
 * Under Option A there is no option table, so renaming `Product Size` to `Size` means
 * rewriting `option_values` on every variant of the product. That is not a form edit and
 * should not feel like one — the button says how many rows it will touch, because "rename"
 * sounds free and this is not.
 *
 * Neither runs as a side effect of typing. Editing an axis name in the option editor
 * changes what FUTURE variants are generated with; it changes nothing already stored until
 * somebody presses the button here.
 *
 * PRESENTATIONAL: the state and the loop live in `ProductEditor`.
 */
import type { RenameSummary } from "@/lib/variant-matrix";

export function RenamePanel({
  summary,
  affectedCount,
  mismatchCount,
  busy,
  error,
  done,
  onApplyRenames,
  onFixNames,
}: {
  summary: RenameSummary;
  /** How many variants a rename would rewrite. */
  affectedCount: number;
  /** How many variants are named something other than their options. */
  mismatchCount: number;
  busy: boolean;
  error: string | null;
  done: string | null;
  onApplyRenames: () => void;
  onFixNames: () => void;
}) {
  const hasRenames = summary.axes.length > 0 || summary.values.length > 0;
  if (!hasRenames && mismatchCount === 0) return null;

  return (
    <div className="rounded-[var(--radius-card)] border border-line p-4">
      <h2 className="text-sm font-medium">Tidy up</h2>

      {error && (
        <p className="mt-3 rounded border border-warn/30 bg-warn/5 p-3 text-sm text-warn">
          {error}
        </p>
      )}
      {done && !error && (
        <p className="mt-3 rounded border border-ok/30 bg-ok/10 p-3 text-sm text-ok" role="status">
          {done}
        </p>
      )}

      {hasRenames && (
        <section className="mt-3">
          <p className="text-sm">
            You renamed{" "}
            {summary.axes.map(([from, to], i) => (
              <span key={from}>
                {i > 0 && ", "}
                <span className="font-medium">{from}</span> to{" "}
                <span className="font-medium">{to}</span>
              </span>
            ))}
            {summary.axes.length > 0 && summary.values.length > 0 && ", and "}
            {summary.values.map(([from, to], i) => (
              <span key={from}>
                {i > 0 && ", "}
                <span className="font-medium">{from}</span> to{" "}
                <span className="font-medium">{to}</span>
              </span>
            ))}
            .
          </p>
          <p className="mt-1 text-xs text-muted">
            {/* The whole reason this is a button and not automatic. */}
            Existing variants still carry the old wording. This rewrites them.
          </p>
          <button
            type="button"
            onClick={onApplyRenames}
            disabled={busy || affectedCount === 0}
            className="mt-2 rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-40"
          >
            {busy
              ? "Renaming…"
              : `Rename on ${affectedCount} ${affectedCount === 1 ? "variant" : "variants"}`}
          </button>
        </section>
      )}

      {mismatchCount > 0 && (
        <section className={hasRenames ? "mt-5 border-t border-line pt-4" : "mt-3"}>
          <p className="text-sm">
            <strong>{mismatchCount}</strong>{" "}
            {mismatchCount === 1 ? "variant is" : "variants are"} not named after their
            options.
          </p>
          <p className="mt-1 text-xs text-muted">
            {/* Why anybody should care: this is the data behind the bug that shipped. */}
            The storefront shows the options, so this is cosmetic there — but the name is
            what appears on order lines and in exports.
          </p>
          <button
            type="button"
            onClick={onFixNames}
            disabled={busy}
            className="mt-2 rounded border border-line px-3 py-1.5 text-sm hover:border-accent disabled:opacity-40"
          >
            {busy ? "Renaming…" : `Name them from their options`}
          </button>
        </section>
      )}
    </div>
  );
}
