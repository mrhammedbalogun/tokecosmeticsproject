"use server";

/**
 * The combo editor's writes.
 *
 * ── ONE PUT, NOT SIX PATCHES ────────────────────────────────────────────────────────
 *
 * `saveComboAction` sends the whole record — fields, item list and pinned prices — in a
 * single request, and the backend replaces the item and price sets wholesale inside the
 * audit mixin's transaction. A bundle assembled by six separate requests can be
 * half-saved, and a half-saved bundle is one that prices wrong on a live page.
 *
 * The image is the exception, and not by preference: a nested `items` array does not
 * survive a multipart encoding (it arrives as flat form fields the serializer reads as
 * garbage), so the file gets its own route. See `ComboAdminViewSet.image`.
 *
 * `fetchWithAuth`, not `fetchWithAuthOrBounce`: a Server Function CAN persist a rotated
 * refresh token, and must — see the dev-time tripwire in `lib/session.ts`.
 */
import { revalidatePath } from "next/cache";
import { ApiError, apiFetchRaw } from "@/lib/api";
import { readAdminCookies } from "@/lib/session";
import { fetchWithAuth } from "@/lib/session";
import type { PickerProduct } from "@/lib/combos";

export interface SaveResult {
  ok?: boolean;
  error?: string;
  fieldErrors?: Record<string, string>;
}

/** DRF's error body is `{field: [msg, …]}` with `detail`/`non_field_errors` for the rest.
 *  Flattened to one string per field, and the first loose message as the headline. */
function readErrors(data: unknown): SaveResult {
  if (!data || typeof data !== "object") {
    return { error: "The combo could not be saved." };
  }
  const body = data as Record<string, unknown>;
  const fieldErrors: Record<string, string> = {};
  let error: string | undefined;
  for (const [key, value] of Object.entries(body)) {
    const message = Array.isArray(value) ? String(value[0]) : String(value);
    if (key === "detail" || key === "non_field_errors" || key === "items" || key === "prices") {
      error ??= message;
    } else {
      fieldErrors[key] = message;
    }
  }
  return { error: error ?? "Some fields need attention.", fieldErrors };
}

export async function saveComboAction(slug: string, payload: unknown): Promise<SaveResult> {
  try {
    await fetchWithAuth(`/admin/combos/${slug}/`, { method: "PATCH", body: payload });
  } catch (e) {
    if (e instanceof ApiError) return readErrors(e.data);
    throw e;
  }
  revalidatePath(`/combos/${slug}`);
  revalidatePath("/combos");
  return { ok: true };
}

/**
 * The featured image. Goes through `apiFetchRaw` with a hand-attached Bearer rather than
 * `fetchWithAuth`, because that helper JSON-encodes its body and this one is a file —
 * `apiFetchRaw` passes a `FormData` through untouched so `fetch` can generate the
 * boundary token, which is the whole reason Content-Type is never set by hand here.
 */
export async function uploadComboImageAction(
  slug: string,
  formData: FormData,
): Promise<SaveResult> {
  const { access } = await readAdminCookies();
  if (!access) return { error: "Your session expired. Reload the page and sign in again." };
  const res = await apiFetchRaw(`/admin/combos/${slug}/image/`, {
    method: "POST",
    body: formData,
    token: access,
  });
  if (!res.ok) {
    const data = await res.json().catch(() => null);
    return readErrors(data);
  }
  revalidatePath(`/combos/${slug}`);
  revalidatePath("/combos");
  return { ok: true };
}

/** The builder's product box. Returns [] rather than throwing on any failure: a search
 *  that errors should read as "nothing found", not blow up an editor holding unsaved work. */
export async function searchProductsAction(term: string): Promise<PickerProduct[]> {
  try {
    return await fetchWithAuth<PickerProduct[]>(
      `/admin/combos/product-search/?q=${encodeURIComponent(term)}`,
    );
  } catch {
    return [];
  }
}
