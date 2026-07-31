/**
 * The Content tab: ingredients, directions, warnings, spec rows and FAQs.
 *
 * ── THIS TAB IS THE TOOL FOR A KNOWN GAP ────────────────────────────────────────────
 *
 * All 69 migrated products have EMPTY ingredients, directions and warnings
 * (`docs/migration/description-review.csv`) — the fields exist in no WordPress column and
 * have to be written fresh. So the empty state here is not an error state: it is the
 * normal starting point for every product in the catalogue, and it should invite typing
 * rather than look broken.
 *
 * `specs` and `faqs` are `JSONField(default=list)` holding `[{label, value}]` and
 * `[{q, a}]`. They get repeatable row editors and not a raw JSON textarea — a textarea
 * makes a syntax error possible in a field where one would break the PDP, and asks a
 * person writing product copy to think about commas and braces.
 *
 * PRESENTATIONAL, like the other panels: no state of its own.
 */
import type { PanelProps } from "@/components/product/DetailsPanel";
import type { FaqRow, SpecRow } from "@/lib/product-form";

const FIELD =
  "w-full rounded border border-line bg-surface px-2 py-1.5 text-sm placeholder:text-muted/70 focus:border-accent focus:outline-none";

const GHOST =
  "rounded border border-line px-2 py-1 text-xs text-muted hover:border-accent hover:text-fg";

function Prose({
  label,
  hint,
  value,
  onChange,
  error,
  rows = 5,
}: {
  label: string;
  hint: string;
  value: string;
  onChange: (value: string) => void;
  error?: string;
  rows?: number;
}) {
  return (
    <label className="block text-xs text-muted">
      {label}
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={rows}
        placeholder={hint}
        className={`mt-1 ${FIELD}`}
      />
      {error && <p className="mt-1 text-xs text-warn">{error}</p>}
    </label>
  );
}

export function ContentPanel({ values, errors, onChange }: PanelProps) {
  const setSpec = (index: number, patch: Partial<SpecRow>) =>
    onChange(
      "specs",
      values.specs.map((row, i) => (i === index ? { ...row, ...patch } : row)),
    );

  const setFaq = (index: number, patch: Partial<FaqRow>) =>
    onChange(
      "faqs",
      values.faqs.map((row, i) => (i === index ? { ...row, ...patch } : row)),
    );

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Prose
        label="Ingredients"
        hint="Shea butter, carrot oil, vitamin E…"
        value={values.ingredients}
        onChange={(v) => onChange("ingredients", v)}
        error={errors.ingredients}
      />
      <Prose
        label="Directions"
        hint="Apply to clean, damp skin morning and night."
        value={values.directions}
        onChange={(v) => onChange("directions", v)}
        error={errors.directions}
      />
      <Prose
        label="Warnings"
        hint="For external use only. Discontinue if irritation occurs."
        value={values.warnings}
        onChange={(v) => onChange("warnings", v)}
        error={errors.warnings}
        rows={3}
      />

      <div className="lg:col-span-2">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium">Specifications</h2>
          <button
            type="button"
            onClick={() => onChange("specs", [...values.specs, { label: "", value: "" }])}
            className={GHOST}
          >
            Add specification
          </button>
        </div>

        {values.specs.length === 0 ? (
          <p className="mt-2 rounded border border-dashed border-line p-4 text-sm text-muted">
            No specifications yet — size, weight, shelf life, that sort of thing.
          </p>
        ) : (
          <div className="mt-2 space-y-2">
            {values.specs.map((row, index) => (
              // Index key, and it is correct here: rows have no id, and the list is only
              // ever appended to or spliced. A content-derived key would change on every
              // keystroke and blur the input mid-word.
              <div key={index} className="flex gap-2">
                <input
                  type="text"
                  value={row.label}
                  onChange={(e) => setSpec(index, { label: e.target.value })}
                  placeholder="Label"
                  aria-label={`Specification ${index + 1} label`}
                  className={`${FIELD} max-w-56`}
                />
                <input
                  type="text"
                  value={row.value}
                  onChange={(e) => setSpec(index, { value: e.target.value })}
                  placeholder="Value"
                  aria-label={`Specification ${index + 1} value`}
                  className={FIELD}
                />
                <button
                  type="button"
                  onClick={() =>
                    onChange(
                      "specs",
                      values.specs.filter((_, i) => i !== index),
                    )
                  }
                  aria-label={`Remove specification ${index + 1}`}
                  className={GHOST}
                >
                  Remove
                </button>
              </div>
            ))}
          </div>
        )}
        {errors.specs && <p className="mt-1 text-xs text-warn">{errors.specs}</p>}
      </div>

      <div className="lg:col-span-2">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium">FAQs</h2>
          <button
            type="button"
            onClick={() => onChange("faqs", [...values.faqs, { q: "", a: "" }])}
            className={GHOST}
          >
            Add question
          </button>
        </div>

        {values.faqs.length === 0 ? (
          <p className="mt-2 rounded border border-dashed border-line p-4 text-sm text-muted">
            No questions yet — the ones customers actually ask are the ones worth adding.
          </p>
        ) : (
          <div className="mt-2 space-y-3">
            {values.faqs.map((row, index) => (
              <div key={index} className="rounded border border-line p-3">
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={row.q}
                    onChange={(e) => setFaq(index, { q: e.target.value })}
                    placeholder="Question"
                    aria-label={`Question ${index + 1}`}
                    className={FIELD}
                  />
                  <button
                    type="button"
                    onClick={() =>
                      onChange(
                        "faqs",
                        values.faqs.filter((_, i) => i !== index),
                      )
                    }
                    aria-label={`Remove question ${index + 1}`}
                    className={GHOST}
                  >
                    Remove
                  </button>
                </div>
                <textarea
                  value={row.a}
                  onChange={(e) => setFaq(index, { a: e.target.value })}
                  rows={2}
                  placeholder="Answer"
                  aria-label={`Answer ${index + 1}`}
                  className={`mt-2 ${FIELD}`}
                />
              </div>
            ))}
          </div>
        )}
        {errors.faqs && <p className="mt-1 text-xs text-warn">{errors.faqs}</p>}
      </div>
    </div>
  );
}
