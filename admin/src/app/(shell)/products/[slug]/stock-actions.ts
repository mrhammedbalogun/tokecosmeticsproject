"use server";

/**
 * The stock adjustment write.
 *
 * A SEPARATE RESOURCE, so a separate action and an immediate effect — not part of the
 * product's Save (17a design decision 1).
 *
 * IT POSTS TO `adjust`, NEVER PATCHES A QUANTITY. `StockItemAdminViewSet` sets
 * `http_method_names = ["get", "post", "head", "options"]` and refuses PUT and PATCH
 * outright; the only route to a number is this action, which requires a reason and a note
 * and writes a `StockMovement`. That is a good constraint, not an obstacle: every quantity
 * change ends up with an author, a reason and a ledger entry.
 *
 * The audit mixin records this as `adjust` rather than `create`, because it prefers the
 * DRF action name over the HTTP verb — which is the whole reason the endpoint is shaped
 * this way.
 */
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";
import type { StockRow } from "@/lib/product-stock";

export interface AdjustResult {
  ok: boolean;
  /** The stock row as saved, so the Variants tab can adopt it without a refetch. */
  item?: StockRow;
  /** Against a field where the backend named one, else a banner message. */
  fieldErrors?: Record<string, string>;
  error?: string;
}

export async function adjustStockAction(input: {
  stockItemId: number;
  quantity: number;
  reason: string;
  note: string;
}): Promise<AdjustResult> {
  const { stockItemId, quantity, reason, note } = input;

  if (!Number.isInteger(stockItemId) || stockItemId < 1) {
    return { ok: false, error: "That stock record could not be identified." };
  }
  // Re-checked server-side because a Server Function is a public endpoint: the modal
  // constrains a browser, not a caller.
  if (!Number.isInteger(quantity) || quantity < 0) {
    return { ok: false, fieldErrors: { quantity: "Enter a whole number, zero or more." } };
  }
  if (!note.trim()) {
    return { ok: false, fieldErrors: { note: "Say why — this goes in the stock ledger." } };
  }

  try {
    const item = await fetchWithAuth<StockRow>(`/admin/stock/${stockItemId}/adjust/`, {
      method: "POST",
      body: { quantity, reason, note },
    });
    // NO revalidatePath — same rule as the image, price and variant writes: in Next 16
    // it would refresh the CURRENT editor page too (~13 API GETs against the per-user
    // throttle), and the admin's pages are all dynamic/no-store so nothing needs it.
    return { ok: true, item };
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    // Post-refresh 401 = the session is dead, not a retryable failure — same mapping
    // as the other action files' message() helpers.
    if (e.status === 401) {
      return { ok: false, error: "Your session has expired — sign in again, then retry." };
    }
    if (e.status === 403) {
      return { ok: false, error: "Your role does not include managing products." };
    }
    if (e.status === 404) return { ok: false, error: "That stock record no longer exists." };

    // DRF answers `{field: ["message"]}` for a bad choice or a blank note. Mapping those
    // back onto the inputs is the difference between "fix the note" and "it did not work".
    const data = e.data as Record<string, unknown> | null;
    if (e.status === 400 && data && typeof data === "object") {
      const fieldErrors: Record<string, string> = {};
      for (const [key, value] of Object.entries(data)) {
        const message = Array.isArray(value) ? value[0] : value;
        if (typeof message === "string") fieldErrors[key] = message;
      }
      if (Object.keys(fieldErrors).length) return { ok: false, fieldErrors };
    }
    return { ok: false, error: "That adjustment could not be saved." };
  }
}
