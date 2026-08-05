"use server";

/** Banner writes (Plan-19c). `marketing.manage` — a banner announces a promotion, so it
 *  is campaign material rather than the legally load-bearing copy `cms.manage` protects. */
import { revalidatePath } from "next/cache";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";

export interface BannerState {
  savedAt?: number;
  fieldErrors?: Record<string, string>;
  message?: string | null;
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
  cta_text: string;
  cta_url: string;
  placement: "hero" | "strip" | "category";
  starts_at: string;
  ends_at: string;
  is_active: boolean;
}): Promise<BannerState> {
  if (!input.title.trim()) return { fieldErrors: { title: "A banner needs a title." } };
  if (input.starts_at && input.ends_at && input.starts_at >= input.ends_at) {
    return { fieldErrors: { ends_at: "The end must come after the start." } };
  }

  const body = {
    title: input.title.trim(),
    subtitle: input.subtitle.trim(),
    cta_text: input.cta_text.trim(),
    cta_url: input.cta_url.trim(),
    placement: input.placement,
    starts_at: input.starts_at || null,
    ends_at: input.ends_at || null,
    is_active: input.is_active,
  };

  try {
    if (input.id) {
      await fetchWithAuth(`/admin/banners/${input.id}/`, { method: "PATCH", body });
    } else {
      await fetchWithAuth("/admin/banners/", { method: "POST", body });
    }
  } catch (e) {
    return fail(e, "That banner could not be saved.");
  }
  revalidatePath("/content/banners");
  return { savedAt: Date.now() };
}

export async function deleteBannerAction(id: number): Promise<BannerState> {
  // Deletion IS offered here, unlike pages: a banner addresses no URL and nothing links
  // to it, so a finished campaign's artwork is genuinely disposable.
  try {
    await fetchWithAuth(`/admin/banners/${id}/`, { method: "DELETE" });
  } catch (e) {
    return fail(e, "That banner could not be removed.");
  }
  revalidatePath("/content/banners");
  return { savedAt: Date.now() };
}

/** Media uploads (landing redesign 2026-08-04): image, mobile image, or VIDEO —
 * all land in the Toke S3 bucket via the backend's FileField, exactly like
 * product images. A separate action from the JSON save for the products
 * pattern's reason: media is multipart and takes effect immediately; the
 * banner's text fields save together on Save. */
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
  // within a minute. Cheap guards, clear sentences.
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
  body.set(kind, file);
  try {
    await fetchWithAuth(`/admin/banners/${id}/`, { method: "PATCH", body });
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    return { message: "The upload was refused — try again." };
  }
  revalidatePath("/content/banners");
  return { message: "Uploaded." };
}
