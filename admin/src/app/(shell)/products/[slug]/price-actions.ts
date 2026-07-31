"use server";

/**
 * Writing one price cell. A separate resource, so a separate write (17a design decision 1)
 * — prices take effect immediately and are not part of the product's Save.
 *
 * ALWAYS A CURRENCY-LEVEL ROW: `country: null`. 17a neither writes nor edits country
 * overrides; the grid refuses those cells before it gets here, and this is the second
 * fence rather than the first.
 *
 * CREATE-OR-UPDATE IS DECIDED BY THE CALLER, from whether the grid found an existing plain
 * row. There is no upsert endpoint, and inventing one client-side by POSTing and retrying
 * on the unique-constraint 400 would write an audit row for the failed attempt.
 */
import { revalidatePath } from "next/cache";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";

export interface PriceWriteResult {
  ok: boolean;
  /** The row as saved, so the grid can adopt its id without refetching. */
  price?: {
    id: number;
    variant: number;
    currency: string;
    country: string | null;
    amount: string;
    starts_at: string | null;
    ends_at: string | null;
  };
  error?: string;
}

function message(e: unknown, fallback: string): string {
  if (!(e instanceof ApiError)) throw e;
  if (e.status === 403) return "Your role does not include managing products.";
  if (e.status === 404) return "That price no longer exists.";
  const data = e.data as Record<string, unknown> | null;
  if (data && typeof data === "object") {
    for (const value of Object.values(data)) {
      if (typeof value === "string") return value;
      if (Array.isArray(value) && typeof value[0] === "string") return value[0];
    }
  }
  return fallback;
}

export async function savePriceAction(input: {
  priceId: number | null;
  variantId: number;
  currency: string;
  amount: string;
  productSlug: string;
}): Promise<PriceWriteResult> {
  const { priceId, variantId, currency, amount } = input;

  if (!Number.isInteger(variantId) || variantId < 1) {
    return { ok: false, error: "That variant could not be identified." };
  }
  if (priceId !== null && (!Number.isInteger(priceId) || priceId < 1)) {
    return { ok: false, error: "That price could not be identified." };
  }
  // Re-checked here because a Server Function is a public endpoint and the grid's own
  // validation constrains a browser, not a caller.
  if (!/^\d+(\.\d{1,2})?$/.test(amount.trim()) || Number(amount) <= 0) {
    return { ok: false, error: "Enter an amount like 1500 or 1500.00." };
  }

  try {
    const price = await fetchWithAuth<PriceWriteResult["price"]>(
      priceId ? `/admin/prices/${priceId}/` : "/admin/prices/",
      {
        method: priceId ? "PATCH" : "POST",
        body: priceId
          ? { amount }
          : { variant: variantId, currency, country: null, amount },
      },
    );
    // The products list's "Unpriced in" column is now stale. The EDITOR page is
    // deliberately not revalidated — that would remount the editor and discard unsaved
    // text in Details or Content, same rule as the image writes.
    revalidatePath("/products");
    return { ok: true, price };
  } catch (e) {
    return { ok: false, error: message(e, "That price could not be saved.") };
  }
}
