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
 * NOTHING IS EVER DELETED HERE. A variant carries price rows, stock rows and links from
 * historical order lines; the builder lists combinations that fall outside the matrix and
 * leaves them alone.
 */
import { revalidatePath } from "next/cache";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";

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

  try {
    const variant = await fetchWithAuth<CreatedVariant>("/admin/variants/", {
      method: "POST",
      body: {
        product: input.productId,
        sku,
        name,
        option_values: input.optionValues,
        // `api_serializers.py:101` picks the default variant and falls back to the first,
        // so a product with none is survivable rather than broken. Still, the FIRST variant
        // a product ever gets should be the default — otherwise the choice is made by row
        // order forever after. Never set on subsequent creates: that would silently demote
        // whichever variant is default today.
        is_default: input.makeDefault,
      },
    });
    // The products list shows a variant count; the editor page is deliberately NOT
    // revalidated, or it would remount and discard unsaved text in another tab.
    revalidatePath("/products");
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
  if (!Object.keys(body).length) {
    return { ok: false, error: "Nothing to change." };
  }

  try {
    const variant = await fetchWithAuth<CreatedVariant>(`/admin/variants/${input.variantId}/`, {
      method: "PATCH",
      body,
    });
    revalidatePath("/products");
    return { ok: true, variant };
  } catch (e) {
    return { ok: false, error: message(e) };
  }
}
