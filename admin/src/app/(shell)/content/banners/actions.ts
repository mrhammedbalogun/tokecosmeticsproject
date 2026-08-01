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
