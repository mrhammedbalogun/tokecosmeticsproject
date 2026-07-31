"use server";

/**
 * The Images tab's three writes: upload, edit, delete.
 *
 * SEPARATE FROM `actions.ts` BECAUSE THEY ARE A SEPARATE RESOURCE (17a design decision 1).
 * The product's own fields save together on Save; images are their own API resource and
 * take effect IMMEDIATELY. Keeping the two in one file would invite a future edit that
 * folded an image write into the product PATCH, which no endpoint supports.
 *
 * TWO ENDPOINTS, DELIBERATELY:
 *
 *   upload  POST /admin/products/{slug}/images/   multipart, binds `product` from the URL
 *   edit    PATCH /admin/images/{id}/             JSON (alt, position, variant)
 *   delete  DELETE /admin/images/{id}/
 *
 * The upload path stays where Plan-05c put it rather than moving onto the images resource,
 * because it owns the multipart parsers and the product binding. `ProductImageAdminViewSet`
 * refuses POST for exactly this reason — two create paths for one model is how the binding
 * rules drift apart.
 *
 * NONE OF THESE REVALIDATE THE EDITOR PAGE. A `revalidatePath` here would re-render the
 * Server Component and remount the editor, discarding whatever unsaved text is sitting in
 * the Details or Content tab — the spec names that as the thing an image failure must not
 * do, and a SUCCESS must not do it either. The client updates its own list from the
 * returned row. `/products` is revalidated because its thumbnail column is now stale and
 * nothing there can be lost.
 */
import { revalidatePath } from "next/cache";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";

export interface ProductImage {
  id: number;
  image: string;
  alt: string;
  position: number;
  variant: number | null;
}

export type ImageResult<T> = { ok: true; value: T } | { ok: false; error: string };

const SLUG = /^[-\w]+$/;

/** Interpolated into a URL path, so the shape is checked before it gets there. `/^\d+$/`
 *  and not `Number(id)`: the latter accepts "1e3", " 1 " and "0x2", each of which
 *  addresses something other than what was clicked. */
const isId = (id: number) => Number.isInteger(id) && id > 0;

function message(e: unknown, fallback: string): string {
  if (!(e instanceof ApiError)) throw e;
  if (e.status === 403) return "Your role does not include managing products.";
  if (e.status === 404) return "That image no longer exists.";
  if (e.status === 413) return "That file is too large.";
  const data = e.data as Record<string, unknown> | null;
  if (data && typeof data === "object") {
    for (const value of Object.values(data)) {
      if (typeof value === "string") return value;
      if (Array.isArray(value) && typeof value[0] === "string") return value[0];
    }
  }
  return fallback;
}

export async function uploadImageAction(
  slug: string,
  formData: FormData,
): Promise<ImageResult<ProductImage>> {
  if (!SLUG.test(slug)) return { ok: false, error: "That product could not be identified." };

  const file = formData.get("image");
  // `instanceof File` rather than a truthiness check: an empty file input still submits an
  // entry, and Django would answer with a less legible version of the same complaint.
  if (!(file instanceof File) || file.size === 0) {
    return { ok: false, error: "Choose a file to upload." };
  }

  try {
    const image = await fetchWithAuth<ProductImage>(
      `/admin/products/${slug}/images/`,
      { method: "POST", body: formData },
    );
    revalidatePath("/products");
    return { ok: true, value: image };
  } catch (e) {
    return { ok: false, error: message(e, "That image could not be uploaded.") };
  }
}

export async function updateImageAction(
  id: number,
  patch: { alt?: string; position?: number; variant?: number | null },
): Promise<ImageResult<ProductImage>> {
  if (!isId(id)) return { ok: false, error: "That image could not be identified." };

  try {
    const image = await fetchWithAuth<ProductImage>(`/admin/images/${id}/`, {
      method: "PATCH",
      body: patch,
    });
    revalidatePath("/products");
    return { ok: true, value: image };
  } catch (e) {
    return { ok: false, error: message(e, "That change could not be saved.") };
  }
}

export async function deleteImageAction(id: number): Promise<ImageResult<null>> {
  if (!isId(id)) return { ok: false, error: "That image could not be identified." };

  try {
    await fetchWithAuth(`/admin/images/${id}/`, { method: "DELETE" });
    revalidatePath("/products");
    return { ok: true, value: null };
  } catch (e) {
    return { ok: false, error: message(e, "That image could not be deleted.") };
  }
}
