/**
 * The Prices grid: variant × currency, and the rule about which cells may be edited.
 *
 * ── WHY THE GRID IS VARIANT × CURRENCY ──────────────────────────────────────────────
 *
 * `Price` hangs off `ProductVariant`, not `Product` (`pricing.Price.variant`). A
 * single-variant product renders as one row of four; the largest production product
 * renders as ten. Describing this as "a row per currency" would be right for 51 products
 * and wrong for the 18 that are multi-variant.
 *
 * ── THE LOCKED-CELL RULE, WHICH IS THE POINT OF THIS FILE ───────────────────────────
 *
 * `Price` has THREE scoping columns beyond variant+currency: `country` (NULL = every
 * country using this currency), `starts_at` and `ends_at`. Its unique constraint is
 * `(variant, currency, country, starts_at)`, so one variant+currency legitimately admits
 * SEVERAL rows — a country override, a scheduled future price, or both.
 *
 * 17a writes plain currency-level rows only: `country = NULL`, `starts_at = NULL`. But it
 * must not PRETEND the others cannot exist. A grid that silently showed the plain row while
 * a narrower one governed some market would let somebody edit a price, see the edit
 * succeed, and change nothing that any customer sees. That is the worst class of bug on
 * this screen, because the failure is indistinguishable from success.
 *
 * So a cell is editable only when the plain row is the ONLY row for that variant+currency.
 * Anything else renders read-only, names what is in the way, and points at 17c.
 *
 * Verified in production 2026-07-30: 121 prices, 0 country overrides, 0 scheduled rows,
 * 0 variant+currency pairs with more than one row. Every locked path below therefore
 * exists only under test today — which is exactly why it is tested rather than deferred.
 */

export interface PriceRow {
  id: number;
  variant: number;
  currency: string;
  country: string | null;
  amount: string;
  starts_at: string | null;
  ends_at: string | null;
}

export interface VariantRow {
  id: number;
  sku: string;
  name: string;
  weight_grams: number | null;
  is_active: boolean;
  position: number;
  /**
   * The option axes this variant sits on, e.g. `{"Product Size": "175g"}`.
   *
   * Declared in Plan-17b: `ProductVariantAdminSerializer` uses `fields = "__all__"`, so the
   * API has always returned this — the type simply under-declared it, and the option-matrix
   * builder would have derived nothing at all from a well-populated response.
   *
   * `{}` on the 52 single-variant products, which is every product that has no options.
   */
  option_values: Record<string, string>;
}

export type Cell =
  | { state: "editable"; price: PriceRow | null; amount: string }
  | { state: "locked"; price: PriceRow | null; amount: string; reason: string };

export interface GridRow {
  variant: VariantRow;
  cells: Record<string, Cell>;
}

/** A row that applies to every country on this currency, always — the only kind 17a
 *  writes, and the only kind it edits. */
const isPlain = (price: PriceRow) => price.country === null && price.starts_at === null;

/**
 * What is in the way of editing this cell, or null if nothing is.
 *
 * Phrased for somebody who is about to type a number into it and needs to know why they
 * cannot — naming the country or the date, not just "locked".
 */
function lockReason(rows: PriceRow[]): string | null {
  const overrides = rows.filter((p) => p.country !== null);
  const scheduled = rows.filter((p) => p.country === null && p.starts_at !== null);

  if (overrides.length) {
    const countries = [...new Set(overrides.map((p) => p.country))].sort().join(", ");
    return `A country-specific price is set for ${countries}, so editing here would not change what those customers pay. Country prices arrive in 17c.`;
  }
  if (scheduled.length) {
    return "A scheduled price exists for this currency, so editing here may not be what customers see. Scheduled prices arrive in 17c.";
  }
  return null;
}

export function buildPriceGrid(
  variants: VariantRow[],
  prices: PriceRow[],
  currencies: readonly string[],
): GridRow[] {
  const byVariant = new Map<number, PriceRow[]>();
  for (const price of prices) {
    const list = byVariant.get(price.variant) ?? [];
    list.push(price);
    byVariant.set(price.variant, list);
  }

  return variants.map((variant) => {
    const own = byVariant.get(variant.id) ?? [];
    const cells: Record<string, Cell> = {};

    for (const currency of currencies) {
      const rows = own.filter((p) => p.currency === currency);
      const plain = rows.find(isPlain) ?? null;
      const reason = lockReason(rows);

      cells[currency] = reason
        ? { state: "locked", price: plain, amount: plain?.amount ?? "", reason }
        : { state: "editable", price: plain, amount: plain?.amount ?? "" };
    }

    return { variant, cells };
  });
}

/** Cells with no price at all — what "invisible in that market for want of a price" looks
 *  like on one product. Production is NGN-only, so this is most of the grid. */
export function missingCount(grid: GridRow[], currencies: readonly string[]): number {
  return grid.reduce(
    (total, row) => total + currencies.filter((c) => !row.cells[c].price).length,
    0,
  );
}

/**
 * Whether a typed amount is worth sending.
 *
 * Rejects what the backend would reject anyway, but with a message against the cell rather
 * than a 400 for the whole grid. A blank string is not invalid — it means "leave this
 * alone"; clearing a price is a DELETE, which 17a does not do.
 */
export function validateAmount(raw: string): string | null {
  const value = raw.trim();
  if (!value) return null;
  // Comma rejected rather than parsed: "1,500" is 1500 to a Nigerian reader and 1.5 to a
  // German one, and guessing wrong writes a price off by a thousand.
  if (value.includes(",")) return "Use a dot for decimals, and no thousands separator.";
  if (!/^\d+(\.\d{1,2})?$/.test(value)) return "Enter an amount like 1500 or 1500.00.";
  if (Number(value) <= 0) return "A price must be more than zero.";
  return null;
}

/** True when the typed value differs from what is stored — so an untouched cell is never
 *  written, and an unchanged one costs no request and no audit row. */
export function amountChanged(cell: Cell, typed: string): boolean {
  const current = cell.price?.amount ?? "";
  if (!typed.trim()) return false;
  if (!current) return true;
  return Number(typed) !== Number(current);
}
