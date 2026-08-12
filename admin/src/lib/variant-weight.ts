/**
 * Parsing a typed weight into `ProductVariant.weight_grams`.
 *
 * One function used by BOTH the editor (so the person typing gets the refusal, next to
 * the field) and the Server Functions (which must re-check regardless — a Server
 * Function is a public endpoint, and the grid only constrains a browser).
 *
 * BLANK MEANS NULL, NEVER 0. The Variants panel renders a missing weight as "—" with a
 * warning precisely because 0 is a claim about a parcel — it is the number a courier
 * quote would be built from (`apps/delivery/services.py` sums `weight_grams or 0`).
 * So "" clears the field, and a literal 0 is refused rather than stored.
 */

export type WeightParse = { ok: true; grams: number | null } | { ok: false; error: string };

/** A sanity ceiling, not the column limit (that is ~2.1 billion). The heaviest thing
 *  this shop ships is a few kilograms; a tonne catches "2500000" where "2500" was
 *  meant before a courier is asked to quote it. */
export const WEIGHT_MAX_GRAMS = 1_000_000;

export function parseWeightInput(text: string): WeightParse {
  const trimmed = text.trim();
  if (trimmed === "") return { ok: true, grams: null };
  if (!/^\d+$/.test(trimmed)) {
    return { ok: false, error: "Weight is whole grams — digits only, e.g. 250." };
  }
  const grams = Number(trimmed);
  if (grams === 0) {
    return { ok: false, error: "Nothing weighs 0 g — leave it blank if unknown." };
  }
  if (grams > WEIGHT_MAX_GRAMS) {
    return { ok: false, error: "That is over a tonne — check the number." };
  }
  return { ok: true, grams };
}

/** Whether a weight the API accepted may be written: null (clear) or a parseable
 *  positive integer. The server-side twin of `parseWeightInput`, for actions whose
 *  input is already a number rather than text. */
export function isValidWeightGrams(value: number | null): boolean {
  if (value === null) return true;
  return Number.isInteger(value) && value >= 1 && value <= WEIGHT_MAX_GRAMS;
}
