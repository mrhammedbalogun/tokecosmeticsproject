"use server";

/** The media library's server actions (2026-08-07).
 *
 * The library exists so an image is uploaded ONCE and attached anywhere — the picker
 * calls `searchMediaAction` as the user types, and every fresh upload goes through
 * `uploadMediaAction` so it lands in the library and is reusable from then on.
 * `marketing.manage`, like the banners it feeds.
 */
import { ApiError } from "@/lib/api";
import type { MediaAssetRow } from "@/lib/media";
import { fetchWithAuth } from "@/lib/session";
import type { UploadTicket } from "@/lib/upload-types";

export interface MediaSearchResult {
  items: MediaAssetRow[];
  hasMore: boolean;
  message?: string;
}

export async function searchMediaAction(input: {
  kind: "image" | "video";
  query: string;
  page: number;
}): Promise<MediaSearchResult> {
  const params = new URLSearchParams({ kind: input.kind, page: String(input.page) });
  if (input.query.trim()) params.set("search", input.query.trim());
  try {
    const data = await fetchWithAuth<{ results: MediaAssetRow[]; next: string | null }>(
      `/admin/media/?${params}`,
    );
    return { items: data.results ?? [], hasMore: Boolean(data.next) };
  } catch {
    return { items: [], hasMore: false, message: "The library could not be loaded." };
  }
}

export interface MediaUploadResult {
  asset?: MediaAssetRow;
  message?: string;
}

export async function uploadMediaAction(formData: FormData): Promise<MediaUploadResult> {
  const file = formData.get("file");
  if (!(file instanceof File) || file.size === 0) {
    return { message: "Choose a file to upload." };
  }
  const body = new FormData();
  body.set("file", file);
  try {
    return { asset: await fetchWithAuth<MediaAssetRow>("/admin/media/", { method: "POST", body }) };
  } catch (e) {
    if (!(e instanceof ApiError)) return { message: "The API is not responding." };
    if (e.status === 413) return { message: "That file is too large for the server." };
    // The API's own sentence ("neither an image nor an mp4/webm video", the size cap)
    // is more useful than a generic one.
    const data = e.data as Record<string, unknown> | undefined;
    const detail = Array.isArray(data?.file) ? data.file[0] : undefined;
    return { message: typeof detail === "string" ? detail : "The upload was refused — try again." };
  }
}

/** Video takes a different route from images (2026-08-09): the browser uploads straight
 * to S3 because Vercel rejects request bodies over ~4.5MB at its edge, before this
 * action would ever run. These two calls are small JSON either side of that upload. */
export async function requestVideoTicketAction(input: {
  filename: string;
  size: number;
  container: "mp4" | "webm";
}): Promise<{ ticket?: UploadTicket; message?: string }> {
  try {
    const ticket = await fetchWithAuth<UploadTicket>("/admin/media/video-ticket/", {
      method: "POST",
      body: input,
    });
    return { ticket };
  } catch (e) {
    if (!(e instanceof ApiError)) return { message: "The API is not responding." };
    const data = e.data as Record<string, unknown> | undefined;
    const detail = Array.isArray(data?.size) ? data.size[0] : undefined;
    return { message: typeof detail === "string" ? detail : "Could not start the upload." };
  }
}

export async function finalizeVideoAction(input: {
  key: string;
  originalName: string;
}): Promise<{ asset?: MediaAssetRow; warning?: string; message?: string }> {
  try {
    const asset = await fetchWithAuth<MediaAssetRow & { warning?: string }>(
      "/admin/media/video-finalize/",
      { method: "POST", body: { key: input.key, original_name: input.originalName } },
    );
    return { asset, warning: asset.warning };
  } catch (e) {
    if (!(e instanceof ApiError)) return { message: "The API is not responding." };
    const data = e.data as Record<string, unknown> | undefined;
    const detail = Array.isArray(data?.key) ? data.key[0] : undefined;
    return { message: typeof detail === "string" ? detail : "The upload could not be verified." };
  }
}
