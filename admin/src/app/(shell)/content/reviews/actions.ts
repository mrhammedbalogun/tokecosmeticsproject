"use server";

/** Google-reviews curation writes (landing redesign 2026-08-04). Same shape as the
 * banner actions: JSON writes, backend messages surfaced verbatim — the backend's
 * "paste the Google share-link" complaint is the useful one. */
import { revalidatePath } from "next/cache";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";

export interface ReviewState {
  message?: string;
  fieldErrors?: Record<string, string>;
}

function fail(e: unknown, fallback: string): ReviewState {
  if (!(e instanceof ApiError)) throw e;
  const data = (e.data ?? {}) as Record<string, unknown>;
  const fieldErrors: Record<string, string> = {};
  for (const [key, value] of Object.entries(data)) {
    const first = Array.isArray(value) ? value[0] : value;
    if (typeof first === "string") fieldErrors[key] = first;
  }
  return Object.keys(fieldErrors).length ? { fieldErrors } : { message: fallback };
}

export async function saveReviewAction(input: {
  id?: number;
  author: string;
  location: string;
  rating: number;
  text: string;
  review_url: string;
  reviewed_at_text: string;
  is_active: boolean;
}): Promise<ReviewState> {
  if (!input.author.trim()) return { fieldErrors: { author: "Who wrote it?" } };
  if (!input.text.trim()) return { fieldErrors: { text: "Paste the review text." } };
  const body = {
    author: input.author.trim(),
    location: input.location.trim(),
    rating: input.rating,
    text: input.text.trim(),
    review_url: input.review_url.trim(),
    reviewed_at_text: input.reviewed_at_text.trim(),
    is_active: input.is_active,
  };
  try {
    if (input.id) {
      await fetchWithAuth(`/admin/google-reviews/${input.id}/`, { method: "PATCH", body });
    } else {
      await fetchWithAuth("/admin/google-reviews/", { method: "POST", body });
    }
  } catch (e) {
    return fail(e, "The review could not be saved.");
  }
  revalidatePath("/content/reviews");
  return { message: "Saved." };
}

export async function deleteReviewAction(id: number): Promise<ReviewState> {
  try {
    await fetchWithAuth(`/admin/google-reviews/${id}/`, { method: "DELETE" });
  } catch (e) {
    return fail(e, "The review could not be removed.");
  }
  revalidatePath("/content/reviews");
  return { message: "Removed." };
}

export async function saveReviewsMetaAction(input: {
  rating: string;
  review_count_text: string;
  profile_url: string;
}): Promise<ReviewState> {
  try {
    await fetchWithAuth("/admin/google-reviews-meta/", {
      method: "PUT",
      body: {
        rating: input.rating,
        review_count_text: input.review_count_text.trim(),
        profile_url: input.profile_url.trim(),
      },
    });
  } catch (e) {
    return fail(e, "The header numbers could not be saved.");
  }
  revalidatePath("/content/reviews");
  return { message: "Saved." };
}
