"use server";

/**
 * The inventory grid's writes.
 *
 * A SERVER FUNCTION, like every other authenticated write in this app: it gets Next's
 * Origin/Host check for free and it may persist a rotated token, which a Server Component
 * may not.
 *
 * ONLY `adjust` LIVES HERE. Creating a stock row where none exists is Plan-17c Task 4, and
 * the grid renders those cells as an absence with nothing to click until it lands — an
 * absence somebody can see is already better than one nobody could.
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
