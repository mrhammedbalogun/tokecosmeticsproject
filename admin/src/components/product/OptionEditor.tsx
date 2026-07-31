"use client";

/**
 * The option editor: the axes a product varies along, and their values.
 *
 * ── NOTHING HERE IS WRITTEN ─────────────────────────────────────────────────────────
 *
 * This is entirely UI state until Generate and Apply (Plan-17b task 3). Editing an axis
 * changes nothing in the database, which is what makes it safe to experiment with a shape
 * before committing to variants that carry prices, stock and order history.
 *
 * ── AXIS ORDER MATTERS AT GENERATION TIME, AND IS NOT PERSISTED ─────────────────────
 *
 * Option A (spec §4) stores options only inside each variant's `option_values`, which is
 * Postgres `jsonb` — keys are ordered by length then bytewise, never by insertion. So the
 * order shown after a reload is not the order anybody chose.
 *
 * It still matters *here*, because the generated variant NAME is the values in axis order:
 * reorder the axes and "175g · Pack Price" becomes "Pack Price · 175g", and that string is
 * stored. Hence the reorder controls, and hence the note saying the order will not survive.
 *
 * PRESENTATIONAL: the axes live in `ProductEditor`, because this panel unmounts on every
 * tab switch and a half-defined matrix must not evaporate on the way to Details and back.
 */
import { useState } from "react";
import { cartesian, MAX_COMBINATIONS, type Axis } from "@/lib/variant-matrix";

const FIELD =
  "rounded border border-line bg-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none";
const GHOST =
  "rounded border border-line px-2 py-1 text-xs text-muted hover:border-accent hover:text-fg disabled:opacity-40";

export function OptionEditor({
  axes,
  errors,
  onChange,
  hasVariants,
}: {
  axes: Axis[];
  errors: string[];
  onChange: (axes: Axis[]) => void;
  /** Whether the product already has variants — changes what the empty state offers. */
  hasVariants: boolean;
}) {
  const [drafts, setDrafts] = useState<Record<number, string>>({});

  const setAxis = (index: number, patch: Partial<Axis>) =>
    onChange(axes.map((axis, i) => (i === index ? { ...axis, ...patch } : axis)));

  const move = <T,>(list: T[], from: number, to: number): T[] => {
    if (to < 0 || to >= list.length) return list;
    const next = [...list];
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    return next;
  };

  const addValue = (index: number) => {
    const value = (drafts[index] ?? "").trim();
    if (!value) return;
    setAxis(index, { values: [...axes[index].values, value] });
    setDrafts({ ...drafts, [index]: "" });
  };

  const total = cartesian(axes).length;

  if (!axes.length) {
    return (
      <div className="rounded-[var(--radius-card)] border border-dashed border-line p-6 text-center">
        <p className="text-sm text-muted">
          {hasVariants
            ? "This product has variants but no option data, so there is no grid to build from."
            : "This product has no options. Most products need none — a single variant is the norm."}
        </p>
        <button
          type="button"
          onClick={() => onChange([{ name: "", values: [] }])}
          className="mt-3 rounded border border-line px-3 py-1.5 text-sm hover:border-accent"
        >
          Add an option
        </button>
      </div>
    );
  }

  return (
    <div className="rounded-[var(--radius-card)] border border-line p-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-sm font-medium">Options</h2>
          <p className="mt-1 text-xs text-muted">
            Nothing here is saved until you generate and apply.
          </p>
        </div>
        <p className="shrink-0 text-xs text-muted" aria-live="polite">
          {total === 0
            ? "No combinations yet"
            : `${total} ${total === 1 ? "combination" : "combinations"}`}
        </p>
      </div>

      {errors.length > 0 && (
        <ul className="mt-3 space-y-1 rounded border border-warn/30 bg-warn/5 p-3 text-sm text-warn">
          {errors.map((error) => (
            <li key={error}>{error}</li>
          ))}
        </ul>
      )}

      <div className="mt-4 space-y-4">
        {axes.map((axis, index) => (
          <div key={index} className="rounded border border-line p-3">
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={axis.name}
                onChange={(e) => setAxis(index, { name: e.target.value })}
                placeholder="Option name, e.g. Size"
                aria-label={`Option ${index + 1} name`}
                className={`${FIELD} flex-1`}
              />
              <button
                type="button"
                onClick={() => onChange(move(axes, index, index - 1))}
                disabled={index === 0}
                aria-label={`Move option ${index + 1} up`}
                className={GHOST}
              >
                ↑
              </button>
              <button
                type="button"
                onClick={() => onChange(move(axes, index, index + 1))}
                disabled={index === axes.length - 1}
                aria-label={`Move option ${index + 1} down`}
                className={GHOST}
              >
                ↓
              </button>
              <button
                type="button"
                onClick={() => onChange(axes.filter((_, i) => i !== index))}
                aria-label={`Remove option ${index + 1}`}
                className={GHOST}
              >
                Remove
              </button>
            </div>

            <div className="mt-3 flex flex-wrap items-center gap-2">
              {axis.values.map((value, valueIndex) => (
                <span
                  key={valueIndex}
                  className="flex items-center gap-1 rounded-full border border-line bg-surface py-1 pl-3 pr-1 text-sm"
                >
                  {value}
                  <button
                    type="button"
                    onClick={() =>
                      setAxis(index, { values: move(axis.values, valueIndex, valueIndex - 1) })
                    }
                    disabled={valueIndex === 0}
                    aria-label={`Move ${value} earlier`}
                    className="px-1 text-xs text-muted hover:text-fg disabled:opacity-30"
                  >
                    ←
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      setAxis(index, { values: move(axis.values, valueIndex, valueIndex + 1) })
                    }
                    disabled={valueIndex === axis.values.length - 1}
                    aria-label={`Move ${value} later`}
                    className="px-1 text-xs text-muted hover:text-fg disabled:opacity-30"
                  >
                    →
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      setAxis(index, { values: axis.values.filter((_, i) => i !== valueIndex) })
                    }
                    aria-label={`Remove ${value}`}
                    className="rounded-full px-1.5 text-xs text-muted hover:text-warn"
                  >
                    ×
                  </button>
                </span>
              ))}

              <span className="flex items-center gap-1">
                <input
                  type="text"
                  value={drafts[index] ?? ""}
                  onChange={(e) => setDrafts({ ...drafts, [index]: e.target.value })}
                  // Enter adds the value rather than submitting anything — this panel sits
                  // inside no form, but the habit is universal and its absence feels broken.
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      addValue(index);
                    }
                  }}
                  placeholder="Add a value"
                  aria-label={`Add a value to option ${index + 1}`}
                  className={`${FIELD} w-36`}
                />
                <button type="button" onClick={() => addValue(index)} className={GHOST}>
                  Add
                </button>
              </span>
            </div>
          </div>
        ))}
      </div>

      <div className="mt-4 flex items-center gap-3">
        <button
          type="button"
          onClick={() => onChange([...axes, { name: "", values: [] }])}
          disabled={total > MAX_COMBINATIONS}
          className={GHOST}
        >
          Add another option
        </button>
        {/* Said once, near the controls it applies to. Pretending the order is remembered
            would be worse than admitting it is not — somebody would spend time arranging
            axes and lose it on the next page load. */}
        <p className="text-xs text-muted">
          Option order affects the generated names, but is not remembered after a reload.
        </p>
      </div>
    </div>
  );
}
