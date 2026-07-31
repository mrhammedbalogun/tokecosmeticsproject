/**
 * The stock adjust form: the reasons on offer, and what a valid entry looks like.
 *
 * ── THE QUANTITY IS ABSOLUTE, NOT A DELTA ───────────────────────────────────────────
 *
 * `inventory.services.adjust(stock_item, new_quantity, ...)` SETS on-hand and records the
 * difference as the movement. So the field means "what the count is now", never "add
 * this many" — and the modal shows the resulting delta so the two readings cannot be
 * confused by somebody who assumed the other one.
 *
 * ── WHY `migration` IS ABSENT ───────────────────────────────────────────────────────
 *
 * `StockAdjustSerializer` excludes it, and the reason is worth repeating where the
 * dropdown is built: `migration` is a machine-only sentinel that
 * `apps/migration_wp/importers/stock.py` reads to find stock nobody has touched since the
 * last import. A human writing it would silently strip that item's clobber guard and
 * expose it to being overwritten by the next migration run.
 */

/** Exactly the choices `StockAdjustSerializer` accepts. Kept in the same order as
 *  `StockMovement.REASONS` so a reader can line the two up. */
export const ADJUST_REASONS = [
  "sale",
  "reservation",
  "release",
  "restock",
  "adjustment",
  "damaged",
  "returned",
] as const;

export type AdjustReason = (typeof ADJUST_REASONS)[number];

/**
 * The reasons a person counting stock actually means, and the ones the order flow writes
 * for itself.
 *
 * BOTH GROUPS ARE OFFERED, because the API accepts both and a dropdown that silently
 * dropped four of them would disagree with the endpoint behind it. But they are separated
 * and labelled: `sale`, `reservation` and `release` are written automatically when an
 * order moves, and a human picking one puts a row in the ledger that reads as though an
 * order caused it. Naming that in the UI is cheaper than explaining it afterwards.
 */
export const REASON_GROUPS: { label: string; reasons: AdjustReason[] }[] = [
  { label: "Counting or correcting", reasons: ["adjustment", "restock", "damaged", "returned"] },
  { label: "Normally automatic", reasons: ["sale", "reservation", "release"] },
];

const LABELS: Record<AdjustReason, string> = {
  sale: "Sale",
  reservation: "Reservation",
  release: "Release",
  restock: "Restock",
  adjustment: "Adjustment / recount",
  damaged: "Damaged",
  returned: "Returned",
};

export function reasonLabel(reason: AdjustReason): string {
  return LABELS[reason];
}

export function isAdjustReason(value: string): value is AdjustReason {
  return (ADJUST_REASONS as readonly string[]).includes(value);
}

export interface AdjustErrors {
  quantity?: string;
  reason?: string;
  note?: string;
}

/**
 * What is wrong with this entry, field by field.
 *
 * Mirrors the serializer rather than inventing rules: `quantity` is
 * `IntegerField(min_value=0)` — zero IS allowed, and it is how a sold-out line is
 * recorded — and `note` is a bare `CharField()`, which rejects blank as well as missing.
 */
export function validateAdjust(input: {
  quantity: string;
  reason: string;
  note: string;
}): AdjustErrors {
  const errors: AdjustErrors = {};

  const quantity = input.quantity.trim();
  if (!quantity) {
    errors.quantity = "Enter the new count.";
  } else if (!/^\d+$/.test(quantity)) {
    // Whole numbers only, and no minus sign: this is a count, and the endpoint refuses a
    // negative one. `Number()` would accept "1e3" and " 1 ", which are not counts anybody
    // typed on purpose.
    errors.quantity = "Enter a whole number, zero or more.";
  }

  if (!isAdjustReason(input.reason)) errors.reason = "Choose a reason.";

  // Required, and deliberately so: a stock write-off with no stated reason is exactly the
  // row somebody will want to read back a month later.
  if (!input.note.trim()) errors.note = "Say why — this goes in the stock ledger.";

  return errors;
}

export const hasErrors = (errors: AdjustErrors) => Object.keys(errors).length > 0;

/**
 * The movement this entry would record: positive added, negative removed.
 *
 * Shown live in the modal because the field is an absolute count while the LEDGER stores a
 * delta, and "47" means very different things depending on whether the shelf held 12 or
 * 300. Returns null while the entry is not yet a number.
 */
export function deltaFor(current: number, typed: string): number | null {
  const value = typed.trim();
  if (!/^\d+$/.test(value)) return null;
  return Number(value) - current;
}
