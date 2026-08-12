"use server";

/**
 * The Videos tab's writes: attach, reorder, detach.
 *
 * THE BYTES NEVER PASS THROUGH HERE. A video upload goes browser → S3 via the media
 * library's ticket/finalize actions (`content/media/actions.ts`) because Vercel kills
 * request bodies over ~4.5MB at its edge — see lib/upload.ts. These actions write only
 * the BINDING: which finalized library asset plays on which product.
 *
 * The upload half runs under `marketing.manage`, the attach under `products.manage`.
 * That split is safe while every products-manage role also holds marketing-manage —
 * pinned by `test_admin_videos.py::test_products_manage_holders_can_reach_the_upload_endpoints`
 * on the API side, and the reason a 403 here and a 403 there get the same wording below.
 *
 * NO `revalidatePath`, same as image-actions.ts: in Next 16 any revalidate in a Server
 * Function refreshes the current route too (~13 API GETs against the per-user throttle
 * per write). The client updates its own list from the returned row.
 */
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";

export interface ProductVideo {
  id: number;
  product: number;
  asset: number;
  position: number;
  /** The asset's URL — CloudFront in prod, Django /media in dev — for the row preview. */
  file: string;
}

export type VideoResult<T> = { ok: true; value: T } | { ok: false; error: string };

const isId = (id: number) => Number.isInteger(id) && id > 0;

function message(e: unknown, fallback: string): string {
  if (!(e instanceof ApiError)) throw e;
  if (e.status === 401) return "Your session has expired — sign in again, then retry.";
  if (e.status === 403) return "Your role does not include managing products.";
  if (e.status === 404) return "That video no longer exists.";
  const data = e.data as Record<string, unknown> | null;
  if (data && typeof data === "object") {
    for (const value of Object.values(data)) {
      if (typeof value === "string") return value;
      if (Array.isArray(value) && typeof value[0] === "string") return value[0];
    }
  }
  return fallback;
}

export async function attachVideoAction(input: {
  productId: number;
  assetId: number;
  position: number;
}): Promise<VideoResult<ProductVideo>> {
  if (!isId(input.productId) || !isId(input.assetId)) {
    return { ok: false, error: "That upload could not be identified." };
  }
  try {
    const video = await fetchWithAuth<ProductVideo>("/admin/videos/", {
      method: "POST",
      body: { product: input.productId, asset: input.assetId, position: input.position },
    });
    return { ok: true, value: video };
  } catch (e) {
    return { ok: false, error: message(e, "That video could not be attached.") };
  }
}

export async function updateVideoAction(
  id: number,
  patch: { position?: number },
): Promise<VideoResult<ProductVideo>> {
  if (!isId(id)) return { ok: false, error: "That video could not be identified." };
  try {
    const video = await fetchWithAuth<ProductVideo>(`/admin/videos/${id}/`, {
      method: "PATCH",
      body: patch,
    });
    return { ok: true, value: video };
  } catch (e) {
    return { ok: false, error: message(e, "That change could not be saved.") };
  }
}

export async function deleteVideoAction(id: number): Promise<VideoResult<null>> {
  if (!isId(id)) return { ok: false, error: "That video could not be identified." };
  try {
    await fetchWithAuth(`/admin/videos/${id}/`, { method: "DELETE" });
    return { ok: true, value: null };
  } catch (e) {
    return { ok: false, error: message(e, "That video could not be removed.") };
  }
}
