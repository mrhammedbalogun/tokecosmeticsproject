"use server";

/**
 * Creating one generated variant.
 *
 * ── ONE AT A TIME, AND THAT IS DELIBERATE ───────────────────────────────────────────
 *
 * There is no bulk endpoint, so a 4 × 2 matrix is eight calls. Building one to get
 * atomicity was refused in the plan: it is a new admin route needing four guard
 * declarations, for a screen used a few times a month. The consequence — a partial apply
 * when call seven collides on SKU — is handled by reporting per row rather than by
 * pretending it cannot happen.
 *
 * THE BUILDER NEVER DELETES. A variant carries price rows, stock rows and links from
 * historical order lines; the builder lists combinations that fall outside the matrix and
 * leaves them alone. Deleting is `deleteVariantAction` below — a deliberate per-row act
 * (products.manage, Owner + Manager, re-checked by the API), never something the
 * matrix arithmetic does on its own.
 */
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";
import { isValidWeightGrams } from "@/lib/variant-weight";

export interface CreatedVariant {
  id: number;
  sku: string;
  name: string;
  option_values: Record<string, string>;
  weight_grams: number | null;
  is_active: boolean;
  position: number;
}

export type VariantCreateResult =
  | { ok: true; variant: CreatedVariant }
  | { ok: false; error: string };

function message(e: unknown): string {
  if (!(e instanceof ApiError)) throw e;
  // A 401 HERE MEANS THE SESSION IS DEAD: fetchWithAuth only rethrows 401 after its
  // silent refresh also failed. Left to the fallback message this read as a retryable
  // save failure, and people retried into the void instead of logging in again.
  if (e.status === 401) return "Your session has expired — sign in again, then retry.";
  if (e.status === 403) return "Your role does not include managing products.";
  const data = e.data as Record<string, unknown> | null;
  if (data && typeof data === "object") {
    // The realistic 400 is a SKU collision, and DRF's own sentence for it names the field
    // and the reason far better than anything invented here would.
    for (const [key, value] of Object.entries(data)) {
      const first = Array.isArray(value) ? value[0] : value;
      if (typeof first === "string") return key === "sku" ? `SKU: ${first}` : first;
    }
  }
  return "That variant could not be created.";
}

export async function createVariantAction(input: {
  productId: number;
  sku: string;
  name: string;
  optionValues: Record<string, string>;
  /** Grams, already parsed by `parseWeightInput`; null = not recorded. Delivery
   *  pricing sums this per line, so it rides along at creation rather than being a
   *  second edit somebody has to remember. */
  weightGrams: number | null;
  /** True only when the product has no variants at all — see below. */
  makeDefault: boolean;
}): Promise<VariantCreateResult> {
  const sku = input.sku.trim();
  const name = input.name.trim();

  if (!Number.isInteger(input.productId) || input.productId < 1) {
    return { ok: false, error: "That product could not be identified." };
  }
  // Re-checked server-side because a Server Function is a public endpoint; the grid
  // constrains a browser, not a caller.
  if (!sku) return { ok: false, error: "A variant needs a SKU." };
  if (sku.length > 64) return { ok: false, error: "That SKU is longer than 64 characters." };
  if (!name) return { ok: false, error: "A variant needs a name." };
  if (!isValidWeightGrams(input.weightGrams)) {
    return { ok: false, error: "Weight must be whole grams (or blank for none)." };
  }

  try {
    const variant = await fetchWithAuth<CreatedVariant>("/admin/variants/", {
      method: "POST",
      body: {
        product: input.productId,
        sku,
        name,
        option_values: input.optionValues,
        weight_grams: input.weightGrams,
        // `api_serializers.py:101` picks the default variant and falls back to the first,
        // so a product with none is survivable rather than broken. Still, the FIRST variant
        // a product ever gets should be the default — otherwise the choice is made by row
        // order forever after. Never set on subsequent creates: that would silently demote
        // whichever variant is default today.
        is_default: input.makeDefault,
      },
    });
    // NO revalidatePath. This runs in a LOOP (one call per generated variant), and in
    // Next 16 any revalidatePath in a Server Function refreshes the current route too —
    // so each call re-rendered the whole editor page (~13 API GETs), and applying a
    // matrix burned ~13× the requests it looked like, against the per-user throttle
    // (measured 2026-08-10). The list's variant count needs nothing from us: the list
    // page is fully dynamic and refetches on every visit.
    return { ok: true, variant };
  } catch (e) {
    return { ok: false, error: message(e) };
  }
}

/**
 * Updating one variant in place — the rename path.
 *
 * Renaming an axis rewrites `option_values` on EVERY variant of the product, so this is
 * called in a loop like the creates, with the same consequence: no transaction, so partial
 * application must be reported rather than hidden. A rename that got halfway would leave a
 * product with two names for one axis, which is precisely the mess it exists to clean up —
 * hence the per-row reporting rather than a single "done".
 */
export async function updateVariantAction(input: {
  variantId: number;
  optionValues?: Record<string, string>;
  name?: string;
  /** Grams; null CLEARS the weight, undefined leaves it alone — the distinction the
   *  rename loop depends on, since it must not touch weights it never read. */
  weightGrams?: number | null;
}): Promise<VariantCreateResult> {
  if (!Number.isInteger(input.variantId) || input.variantId < 1) {
    return { ok: false, error: "That variant could not be identified." };
  }

  const body: Record<string, unknown> = {};
  if (input.optionValues) body.option_values = input.optionValues;
  if (input.name !== undefined) {
    const name = input.name.trim();
    if (!name) return { ok: false, error: "A variant needs a name." };
    body.name = name;
  }
  if (input.weightGrams !== undefined) {
    if (!isValidWeightGrams(input.weightGrams)) {
      return { ok: false, error: "Weight must be whole grams (or blank for none)." };
    }
    body.weight_grams = input.weightGrams;
  }
  if (!Object.keys(body).length) {
    return { ok: false, error: "Nothing to change." };
  }

  try {
    const variant = await fetchWithAuth<CreatedVariant>(`/admin/variants/${input.variantId}/`, {
      method: "PATCH",
      body,
    });
    return { ok: true, variant };
  } catch (e) {
    return { ok: false, error: message(e) };
  }
}

export type VariantDeleteResult = { ok: true } | { ok: false; error: string };

/**
 * Deleting one variant. The API cascades its price rows, stock rows and any live cart
 * lines holding it (order history survives via its own snapshots), promotes a new
 * default when the default is deleted, and refuses to delete a product's LAST variant —
 * that refusal's `detail` sentence is surfaced verbatim below.
 */
export async function deleteVariantAction(input: {
  variantId: number;
}): Promise<VariantDeleteResult> {
  if (!Number.isInteger(input.variantId) || input.variantId < 1) {
    return { ok: false, error: "That variant could not be identified." };
  }

  try {
    await fetchWithAuth(`/admin/variants/${input.variantId}/`, { method: "DELETE" });
    return { ok: true };
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    if (e.status === 401) {
      return { ok: false, error: "Your session has expired — sign in again, then retry." };
    }
    if (e.status === 403) return { ok: false, error: "Your role does not include managing products." };
    if (e.status === 404) return { ok: false, error: "That variant no longer exists." };
    const data = e.data as Record<string, unknown> | null;
    if (data && typeof data === "object") {
      // The realistic 400 is the last-variant refusal, whose `detail` names the fix.
      for (const value of Object.values(data)) {
        const first = Array.isArray(value) ? value[0] : value;
        if (typeof first === "string") return { ok: false, error: first };
      }
    }
    return { ok: false, error: "That variant could not be deleted." };
  }
}
