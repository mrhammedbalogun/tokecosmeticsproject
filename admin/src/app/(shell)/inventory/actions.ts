"use server";

/**
 * The inventory grid's writes.
 *
 * A SERVER FUNCTION, like every other authenticated write in this app: it gets Next's
 * Origin/Host check for free and it may persist a rotated token, which a Server Component
 * may not.
 *
 * VALIDATION HERE IS NOT THE CONTROL. `StockAdjustSerializer` requires a reason and a note
 * and refuses `migration`; `HasAdminScope("products.manage")` gates the call. What the
 * checks below buy is a legible message instead of a 400 rendered as "something went wrong".
 */
import { revalidatePath } from "next/cache";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";
import { ADJUST_REASONS, type AdjustErrors } from "@/lib/stock-adjust";

export interface AdjustState {
  ok?: boolean;
  errors?: AdjustErrors;
  message?: string | null;
}

export async function adjustStockAction(input: {
  stockItemId: number;
  quantity: number;
  reason: string;
  note: string;
}): Promise<AdjustState> {
  if (!Number.isInteger(input.stockItemId) || input.stockItemId <= 0) {
    return { message: "That stock row could not be identified." };
  }
  if (!Number.isInteger(input.quantity) || input.quantity < 0) {
    return { errors: { quantity: "Enter the count as a whole number, 0 or more." } };
  }
  if (!(ADJUST_REASONS as readonly string[]).includes(input.reason)) {
    return { errors: { reason: "Pick a reason." } };
  }
  if (!input.note.trim()) {
    return { errors: { note: "Say why — this is the line somebody reads back later." } };
  }

  try {
    await fetchWithAuth(`/admin/stock/${input.stockItemId}/adjust/`, {
      method: "POST",
      body: {
        quantity: input.quantity,
        reason: input.reason,
        note: input.note.trim(),
      },
    });
  } catch (e) {
    if (e instanceof ApiError) {
      const data = e.data as Record<string, unknown> | undefined;
      const field = (key: string): string | undefined => {
        const value = data?.[key];
        if (Array.isArray(value) && typeof value[0] === "string") return value[0];
        return typeof value === "string" ? value : undefined;
      };
      const errors: AdjustErrors = {};
      const quantity = field("quantity");
      const reason = field("reason");
      const note = field("note");
      if (quantity) errors.quantity = quantity;
      if (reason) errors.reason = reason;
      if (note) errors.note = note;
      if (Object.keys(errors).length) return { errors };
      return { message: field("detail") ?? "The adjustment was refused." };
    }
    return { message: "The API is not responding." };
  }

  revalidatePath("/inventory");
  return { ok: true };
}

export interface StartStockingState {
  ok?: boolean;
  /** Set when the row was created but the opening count did not land — see below. */
  partial?: boolean;
  errors?: AdjustErrors & { threshold?: string };
  message?: string | null;
}

/**
 * Start stocking a variant in a warehouse that has no row for it — Plan-17c Task 4, and
 * the gap 17a Task 7 recorded.
 *
 * ── TWO WRITES, AND THAT IS DELIBERATE ──────────────────────────────────────────────
 *
 * `StockItemSerializer` makes `quantity` read-only: numbers move only through `adjust()`,
 * so every change lands in the movement ledger with a reason, a note and an actor. That
 * rule is worth more than the convenience of a single call, so this creates the row at
 * zero and then adjusts it to the opening count — and the ledger reads "somebody put 40
 * units here, for this reason" rather than a row that simply appeared holding stock.
 *
 * An opening count of ZERO skips the second write entirely. "We stock this here but hold
 * none today" is a real thing to record, and inventing a 0 → 0 movement to say it would
 * put a line in the ledger describing nothing.
 *
 * IF THE SECOND WRITE FAILS the row still exists, at zero. That is reported as `partial`
 * rather than as a failure, because it is recoverable in one click from the grid the
 * caller is already looking at — and telling somebody "that failed" when a row now exists
 * would send them to create it again and meet a duplicate error.
 */
export async function startStockingAction(input: {
  variantId: number;
  warehouseId: number;
  quantity: number;
  threshold: number;
  reason: string;
  note: string;
}): Promise<StartStockingState> {
  if (!Number.isInteger(input.variantId) || !Number.isInteger(input.warehouseId)) {
    return { message: "That variant or warehouse could not be identified." };
  }
  if (!Number.isInteger(input.quantity) || input.quantity < 0) {
    return { errors: { quantity: "Enter the opening count as a whole number, 0 or more." } };
  }
  if (!Number.isInteger(input.threshold) || input.threshold < 0) {
    return { errors: { threshold: "Enter the low-stock threshold as a whole number." } };
  }
  if (input.quantity > 0) {
    if (!(ADJUST_REASONS as readonly string[]).includes(input.reason)) {
      return { errors: { reason: "Pick a reason." } };
    }
    if (!input.note.trim()) {
      return { errors: { note: "Say where this stock came from." } };
    }
  }

  let stockItemId: number;
  try {
    const created = await fetchWithAuth<{ id: number }>("/admin/stock/", {
      method: "POST",
      body: {
        variant: input.variantId,
        warehouse: input.warehouseId,
        low_stock_threshold: input.threshold,
      },
    });
    stockItemId = created.id;
  } catch (e) {
    if (e instanceof ApiError) {
      // The duplicate case is worth its own sentence: `unique_together` means somebody
      // else got there first, and "reload" is the fix rather than "try again".
      const data = e.data as Record<string, unknown> | undefined;
      const nonField = Array.isArray(data?.non_field_errors) ? data.non_field_errors[0] : null;
      if (e.status === 400) {
        return {
          message:
            typeof nonField === "string" && /unique|already/i.test(nonField)
              ? "This variant is already stocked in that warehouse. Reload the page."
              : "That stock row could not be created.",
        };
      }
      return { message: "That stock row could not be created." };
    }
    return { message: "The API is not responding." };
  }

  if (input.quantity > 0) {
    const adjusted = await adjustStockAction({
      stockItemId,
      quantity: input.quantity,
      reason: input.reason,
      note: input.note,
    });
    if (!adjusted.ok) {
      revalidatePath("/inventory");
      return {
        partial: true,
        errors: adjusted.errors,
        message:
          "The row was created but the opening count was not recorded. It is showing 0 — adjust it from the grid.",
      };
    }
  }

  revalidatePath("/inventory");
  return { ok: true };
}
