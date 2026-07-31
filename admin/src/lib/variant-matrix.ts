/**
 * The option-matrix builder's arithmetic. No React, no fetching — Plan-17b Task 1.
 *
 * ── OPTION DEFINITIONS ARE DERIVED, NOT STORED (spec §4, Option A) ──────────────────
 *
 * There is no `ProductOption` table. A product's axes exist only as an emergent property
 * of its variants' `option_values`, so `deriveAxes` reads them back out and the editor
 * holds the rest in browser state until Apply writes plain dicts again.
 *
 * The accepted cost: **axis order is arbitrary**. Django stores `option_values` as Postgres
 * `jsonb`, which orders keys by length then bytewise rather than by insertion, so no order
 * anybody chooses can be persisted. It is stable between reads — the builder will not
 * reshuffle under a user — it is simply not theirs. The UI says so once.
 */

export interface Axis {
  name: string;
  values: string[];
}

/** One point in the grid: axis name → value. */
export type Combination = Record<string, string>;

/** A variant, narrowed to what the matrix cares about. */
export interface MatrixVariant {
  id: number;
  sku: string;
  name: string;
  option_values: Record<string, string>;
}

/**
 * The ceiling on generated combinations.
 *
 * Three axes of five values is 125 variants, each carrying price and stock rows, created by
 * 125 sequential POSTs against an API with no bulk endpoint. Nothing in production comes
 * near it — the largest real matrix is 4 × 2. The limit exists because a builder puts that
 * mistake one careless click away, and undoing it means deleting variants, which Apply
 * deliberately cannot do.
 */
export const MAX_COMBINATIONS = 50;

/** `ProductVariant.sku` is `CharField(max_length=64)`. A longer suggestion is a guaranteed
 *  400 that reads as a bug in the builder rather than as a too-long name. */
export const SKU_MAX = 64;

/**
 * The axes a product already has, read back off its variants.
 *
 * Axis order follows first appearance across the variant list, and value order follows
 * first appearance within each axis — so the result is stable for stable input, which is
 * what stops the editor reshuffling between renders.
 */
export function deriveAxes(variants: MatrixVariant[]): Axis[] {
  const values = new Map<string, string[]>();

  for (const variant of variants) {
    for (const [name, value] of Object.entries(variant.option_values ?? {})) {
      const seen = values.get(name) ?? [];
      if (!seen.includes(value)) seen.push(value);
      values.set(name, seen);
    }
  }

  return [...values.entries()].map(([name, vals]) => ({ name, values: vals }));
}

/**
 * Every combination of the given axes, last axis varying fastest.
 *
 * Odometer order, so the first axis reads as the grouping — all the 175g rows together,
 * then all the 275g rows. That is how somebody scanning the grid expects to find a row.
 *
 * An axis with no values yields NO combinations rather than being skipped: a half-defined
 * axis means the grid is not ready, and quietly ignoring it would generate variants that
 * omit an axis the user is in the middle of adding.
 */
export function cartesian(axes: Axis[]): Combination[] {
  if (!axes.length) return [];
  if (axes.some((axis) => axis.values.length === 0)) return [];

  let out: Combination[] = [{}];
  for (const axis of axes) {
    const next: Combination[] = [];
    for (const partial of out) {
      for (const value of axis.values) next.push({ ...partial, [axis.name]: value });
    }
    out = next;
  }
  return out;
}

export interface MatrixDiff {
  /** Combinations that already have a variant. */
  existing: { combination: Combination; variant: MatrixVariant }[];
  /** Combinations with no variant yet — what Apply would create. */
  missing: Combination[];
  /** Variants matching no combination. Listed, never deleted. */
  orphaned: MatrixVariant[];
}

/**
 * What Apply would do, without doing it.
 *
 * A variant matches a combination on an EXACT key-set match — same axes, same values.
 * A subset does not match, and that has a consequence worth stating: **adding an axis
 * orphans every existing variant**, because none of them has a value for it. Guessing one
 * would invent data. Apply never deletes, so nothing is lost, but the UI has to say this
 * before somebody generates a parallel set of variants beside their real ones.
 */
export function diffMatrix(
  combinations: Combination[],
  variants: MatrixVariant[],
): MatrixDiff {
  const claimed = new Set<number>();
  const existing: MatrixDiff["existing"] = [];
  const missing: Combination[] = [];

  for (const combination of combinations) {
    const match = variants.find(
      (variant) => !claimed.has(variant.id) && sameOptions(variant.option_values, combination),
    );
    if (match) {
      claimed.add(match.id);
      existing.push({ combination, variant: match });
    } else {
      missing.push(combination);
    }
  }

  return {
    existing,
    missing,
    orphaned: variants.filter((variant) => !claimed.has(variant.id)),
  };
}

/** Key-order-insensitive equality — jsonb does not preserve the order the values were
 *  written in, so comparing serialised forms would report false differences. */
function sameOptions(a: Record<string, string>, b: Record<string, string>): boolean {
  const aKeys = Object.keys(a ?? {});
  const bKeys = Object.keys(b ?? {});
  if (aKeys.length !== bKeys.length) return false;
  return aKeys.every((key) => key in b && a[key] === b[key]);
}

/**
 * The name a generated variant gets: its option values, joined.
 *
 * The separator matches `storefront/src/lib/variant-label.ts`. That file exists because the
 * picker used to render `variant.name`, which on these products was the PRODUCT's name —
 * seven identical buttons at seven prices. A builder that named variants any other way
 * would put admin and storefront back out of step, one product at a time.
 */
export function variantName(combination: Combination): string {
  return Object.values(combination)
    .map((value) => value.trim())
    .filter(Boolean)
    .join(" · ");
}

/**
 * A suggested SKU: the product slug plus the option values, slugified.
 *
 * Editable in the grid — this is a starting point, not a scheme. `sku` is unique across the
 * WHOLE table, so `taken` (the SKUs already on screen, plus any generated so far this pass)
 * is deduplicated against here rather than discovered as a 400 on Apply.
 */
export function suggestSku(
  productSlug: string,
  combination: Combination,
  taken: readonly string[],
): string {
  const parts = [productSlug, ...Object.values(combination)].map(slugPart).filter(Boolean);
  const base = clamp(parts.join("-"), SKU_MAX);

  if (!taken.includes(base)) return base;

  // Suffix, and re-clamp so the counter cannot push it past the column. Truncation can make
  // two different combinations collide, which is exactly when the counter is needed.
  for (let n = 2; n < 1000; n++) {
    const suffix = `-${n}`;
    const candidate = `${clamp(base, SKU_MAX - suffix.length)}${suffix}`;
    if (!taken.includes(candidate)) return candidate;
  }
  return base;
}

function slugPart(value: string): string {
  return value
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^\w\s-]/g, "")
    .trim()
    .replace(/[-\s_]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function clamp(value: string, max: number): string {
  return value.length <= max ? value : value.slice(0, max).replace(/-+$/, "");
}

/**
 * Everything wrong with the axes as they stand, in the order a person would fix it.
 *
 * Returns messages rather than a boolean because the editor shows them all at once —
 * fixing one blank value only to be told about the next is three round trips through the
 * same form.
 */
export function validateAxes(axes: Axis[]): string[] {
  const errors: string[] = [];
  const seenNames = new Set<string>();

  for (const axis of axes) {
    const name = axis.name.trim();
    if (!name) {
      errors.push("Every option needs a name.");
    } else {
      // Case- and padding-insensitive: "Size" and " size " would collapse into one key on
      // write, silently losing an axis and half the grid with it.
      const key = name.toLowerCase();
      if (seenNames.has(key)) errors.push(`“${name}” is listed twice — each option needs its own name.`);
      seenNames.add(key);
    }

    const label = name || "That option";
    if (!axis.values.length) {
      errors.push(`${label} has no values yet.`);
      continue;
    }

    const seenValues = new Set<string>();
    for (const value of axis.values) {
      const trimmed = value.trim();
      if (!trimmed) {
        errors.push(`${label} has a blank value.`);
        continue;
      }
      const key = trimmed.toLowerCase();
      if (seenValues.has(key)) errors.push(`${label} lists “${trimmed}” twice.`);
      seenValues.add(key);
    }
  }

  const total = axes.reduce((n, axis) => n * Math.max(axis.values.length, 0), 1);
  if (axes.length && total > MAX_COMBINATIONS) {
    errors.push(
      `That is ${total} variants, and ${MAX_COMBINATIONS} is the most this can create at ` +
        `once. Each one carries its own prices and stock, and they cannot be deleted here.`,
    );
  }

  return errors;
}

// ── Renaming ────────────────────────────────────────────────────────────────────────
//
// The migration-debris fix. `Product Size` (55 production variants) and `Size` (12) are the
// same axis under two WooCommerce labels, and under Option A the only way to correct that is
// to rewrite `option_values` on every variant of the product.
//
// That makes renaming a BULK WRITE, not a form edit, which is why it is detected explicitly
// and confirmed with a count rather than happening as a side effect of typing.

export interface RenameSummary {
  /** `[from, to]` for each axis whose name changed. */
  axes: [string, string][];
  /** `[from, to]` for each value that changed, within an unchanged axis. */
  values: [string, string][];
}

/**
 * Whether two axis lists describe the same SHAPE — same axis count, same value count per
 * axis — so that position can be trusted to identify what was renamed.
 *
 * If somebody has added an axis or removed a value, they are restructuring rather than
 * renaming, and position no longer means anything. Renames are simply not offered then.
 */
export function structuresMatch(a: Axis[], b: Axis[]): boolean {
  if (a.length !== b.length) return false;
  return a.every((axis, i) => axis.values.length === b[i].values.length);
}

/** What changed in name only, between the axes as stored and the axes as edited. */
export function renameSummary(derived: Axis[], current: Axis[]): RenameSummary {
  const summary: RenameSummary = { axes: [], values: [] };
  if (!structuresMatch(derived, current)) return summary;

  derived.forEach((axis, i) => {
    const now = current[i];
    if (axis.name !== now.name) summary.axes.push([axis.name, now.name]);
    axis.values.forEach((value, j) => {
      if (value !== now.values[j]) summary.values.push([value, now.values[j]]);
    });
  });

  return summary;
}

/**
 * One variant's `option_values`, rewritten through a rename.
 *
 * Keyed by POSITION in the axis list rather than by matching old names to new ones: a swap
 * (`Size` → `Shade`, `Shade` → `Size`) would be ambiguous by name and is unambiguous by
 * index. Anything the variant carries that the axes do not describe is left untouched
 * rather than dropped — this rewrites what it recognises and preserves what it does not.
 */
export function remapOptions(
  options: Record<string, string>,
  derived: Axis[],
  current: Axis[],
): Record<string, string> {
  if (!structuresMatch(derived, current)) return { ...options };

  const out: Record<string, string> = {};
  const handled = new Set<string>();

  derived.forEach((axis, i) => {
    if (!(axis.name in options)) return;
    handled.add(axis.name);
    const value = options[axis.name];
    const valueIndex = axis.values.indexOf(value);
    out[current[i].name] = valueIndex >= 0 ? current[i].values[valueIndex] : value;
  });

  for (const [key, value] of Object.entries(options)) {
    if (!handled.has(key)) out[key] = value;
  }
  return out;
}

/**
 * Variants whose stored `name` is not what their options say it should be.
 *
 * On the 8 two-axis production products every variant is named after the PRODUCT — which is
 * the defect `storefront/src/lib/variant-label.ts` had to work around. Fixing the stored
 * names is offered explicitly and never done as a side effect: it is a bulk write, and
 * `name` is what appears on order lines already placed.
 */
export function nameMismatches(variants: MatrixVariant[]): MatrixVariant[] {
  return variants.filter((variant) => {
    const expected = variantName(variant.option_values ?? {});
    return expected !== "" && expected !== variant.name;
  });
}

/**
 * The server's variant list merged with the ones created this session, without doubles.
 *
 * After Apply, a created variant exists in two places at once: in `newVariants` (state,
 * so the grid shows it immediately) and — as soon as the revalidated page data lands — in
 * the server-rendered `variants` prop as well. Concatenating the two rendered every fresh
 * row twice, with the row's id as a duplicated React key, and fed the doubled list into
 * the next Generate, whose diff then reported "8 outside this matrix" on a product with 4.
 * The server copy wins here; the session copy only fills the gap until it arrives.
 */
export function mergeVariants<V extends { id: number }>(server: V[], created: V[]): V[] {
  const known = new Set(server.map((variant) => variant.id));
  return [...server, ...created.filter((variant) => !known.has(variant.id))];
}
