"use server";

/** Banner writes (Plan-19c). `marketing.manage` — a banner announces a promotion, so it
 *  is campaign material rather than the legally load-bearing copy `cms.manage` protects. */
import { revalidatePath } from "next/cache";
import { uploadMediaAction } from "@/app/(shell)/content/media/actions";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";

export interface BannerState {
  savedAt?: number;
  /** The banner's id — on create, the id the API just assigned, so the editor can
   * attach staged media to the row it has only now learned the name of. */
  id?: number;
  fieldErrors?: Record<string, string>;
  message?: string | null;
}

/**
 * Every screen that edits a banner, refreshed together.
 *
 * These actions do not know WHICH placement the caller was editing — and even if they
 * did, one banner list feeds more than one screen. /home-content owns the landing page's
 * placements; /content/affiliates owns the two on the referral page (added 2026-08-16).
 * Refreshing only the first meant a marketer could upload the affiliate hero and watch
 * the tile stay empty until they reloaded by hand.
 *
 * If a third screen ever edits banners, add it here — a missing entry fails silently,
 * which is the worst way for this to be wrong.
 */
const BANNER_SCREENS = ["/home-content", "/content/affiliates"] as const;

function revalidateHome() {
  for (const path of BANNER_SCREENS) revalidatePath(path);
}

function fail(e: unknown, fallback: string): BannerState {
  if (!(e instanceof ApiError)) return { message: "The API is not responding." };
  const data = e.data as Record<string, unknown> | undefined;
  const fieldErrors: Record<string, string> = {};
  for (const [key, value] of Object.entries(data ?? {})) {
    const first = Array.isArray(value) ? value[0] : value;
    if (typeof first === "string") fieldErrors[key] = first;
  }
  return Object.keys(fieldErrors).length ? { fieldErrors } : { message: fallback };
}

export async function saveBannerAction(input: {
  id?: number;
  title: string;
  subtitle: string;
  tagline: string;
  cta_text: string;
  cta_url: string;
  placement: string;
  sort: number;
  starts_at: string;
  ends_at: string;
  is_active: boolean;
  /** Country codes the banner is limited to; empty means everywhere. */
  countries: string[];
  /** How an attached video plays on the storefront. */
  video_mode: "loop" | "click";
}): Promise<BannerState> {
  if (!input.title.trim()) return { fieldErrors: { title: "A banner needs a title." } };
  if (input.starts_at && input.ends_at && input.starts_at >= input.ends_at) {
    return { fieldErrors: { ends_at: "The end must come after the start." } };
  }

  const body = {
    title: input.title.trim(),
    subtitle: input.subtitle.trim(),
    tagline: input.tagline.trim(),
    cta_text: input.cta_text.trim(),
    cta_url: input.cta_url.trim(),
    placement: input.placement,
    sort: input.sort,
    starts_at: input.starts_at || null,
    ends_at: input.ends_at || null,
    is_active: input.is_active,
    countries: input.countries,
    video_mode: input.video_mode,
  };

  let saved: { id: number };
  try {
    if (input.id) {
      saved = await fetchWithAuth<{ id: number }>(`/admin/banners/${input.id}/`, {
        method: "PATCH",
        body,
      });
    } else {
      saved = await fetchWithAuth<{ id: number }>("/admin/banners/", { method: "POST", body });
    }
  } catch (e) {
    return fail(e, "That banner could not be saved.");
  }
  revalidateHome();
  return { savedAt: Date.now(), id: saved.id };
}

export async function deleteBannerAction(id: number): Promise<BannerState> {
  // Deletion IS offered here, unlike pages: a banner addresses no URL and nothing links
  // to it, so a finished campaign's artwork is genuinely disposable.
  try {
    await fetchWithAuth(`/admin/banners/${id}/`, { method: "DELETE" });
  } catch (e) {
    return fail(e, "That banner could not be removed.");
  }
  revalidateHome();
  return { savedAt: Date.now() };
}

/**
 * Rewrite a placement's order in one move: `orderedIds` is the FULL lineup for that
 * placement (live and waiting alike), and each banner's `sort` becomes its index. Sending
 * the whole lineup rather than a swapped pair normalises legacy rows that all sat at
 * sort 0, where a pairwise swap would be a no-op.
 */
export async function reorderBannersAction(orderedIds: number[]): Promise<BannerState> {
  try {
    for (const [index, id] of orderedIds.entries()) {
      await fetchWithAuth(`/admin/banners/${id}/`, { method: "PATCH", body: { sort: index } });
    }
  } catch (e) {
    return fail(e, "The new order could not be saved.");
  }
  revalidateHome();
  return { savedAt: Date.now() };
}

/** Media uploads (landing redesign 2026-08-04; rerouted through the media library
 * 2026-08-07): the file is uploaded ONCE into `/admin/media/` and the banner is then
 * attached to the new asset by id — so every upload automatically becomes reusable
 * from the library picker. If the attach fails after the upload succeeded, the file
 * simply sits in the library, visible and pickable: a harmless partial failure. */
export async function uploadBannerMediaAction(
  id: number,
  kind: "image" | "mobile_image" | "video",
  formData: FormData,
): Promise<BannerState> {
  const file = formData.get("file");
  if (!(file instanceof File) || file.size === 0) {
    return { message: "Choose a file to upload." };
  }
  // Hero videos autoplay on the shop's front door; a wrong file here is customer-facing
  // within a minute. Cheap guards with clear sentences — the API re-checks by sniffing
  // the bytes, so these only exist to answer faster.
  if (kind === "video" && !file.type.startsWith("video/")) {
    return { message: "That is not a video file (mp4 or webm)." };
  }
  if (kind !== "video" && !file.type.startsWith("image/")) {
    return { message: "That is not an image file." };
  }
  if (file.size > 80 * 1024 * 1024) {
    return { message: "Keep uploads under 80 MB — compress the video first." };
  }
  const body = new FormData();
  body.set("file", file);
  const uploaded = await uploadMediaAction(body);
  if (!uploaded.asset) return { message: uploaded.message ?? "The upload was refused — try again." };
  return attachBannerMediaAction(id, kind, uploaded.asset.id);
}

/** Point a banner slot at an EXISTING library asset — no bytes move; the two rows
 * share one S3 object. The API refuses a kind mismatch (a video into an image slot). */
export async function attachBannerMediaAction(
  id: number,
  kind: "image" | "mobile_image" | "video",
  assetId: number,
): Promise<BannerState> {
  try {
    await fetchWithAuth(`/admin/banners/${id}/`, {
      method: "PATCH",
      body: { [`${kind}_asset`]: assetId },
    });
  } catch (e) {
    return fail(e, "That file could not be attached.");
  }
  revalidateHome();
  return { savedAt: Date.now() };
}

/** Detach a banner's image or video (the FileFields are blank=True, so null clears). */
export async function clearBannerMediaAction(
  id: number,
  kind: "image" | "mobile_image" | "video",
): Promise<BannerState> {
  try {
    await fetchWithAuth(`/admin/banners/${id}/`, { method: "PATCH", body: { [kind]: null } });
  } catch (e) {
    return fail(e, "The file could not be removed.");
  }
  revalidateHome();
  return { savedAt: Date.now() };
}
