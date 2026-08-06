"use server";

/**
 * Submit a product review. A Server Function for the same reasons as the profile
 * form: Next's Origin/Host CSRF check comes free, and `fetchWithAuth` may run its
 * silent 401→refresh→retry here because a Server Function can write cookies.
 *
 * Reviews publish immediately (admin can hide/delete after the fact), so success
 * expires the product tag with `updateTag` — the read-your-own-writes API (bundled
 * docs, updateTag.md): the next request WAITS for fresh data instead of serving the
 * stale list, so the customer's own review is visible on the very next render.
 */
import { updateTag } from "next/cache";
import { fetchWithAuth } from "@/lib/session";
import { ApiError } from "@/lib/api";
import { accountErrorMessage } from "@/lib/auth-errors";

export interface ReviewFormState {
  submitted?: boolean;
  error?: string;
}

const FALLBACK = "We couldn't submit your review — please try again.";

function field(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value.trim() : "";
}

export async function submitReviewAction(
  _prevState: ReviewFormState,
  formData: FormData,
): Promise<ReviewFormState> {
  const slug = field(formData, "slug");
  const rating = Number(field(formData, "rating"));
  const body = field(formData, "body");

  if (!slug) return { error: FALLBACK };
  if (!Number.isInteger(rating) || rating < 1 || rating > 5) {
    return { error: "Choose a star rating." };
  }
  if (!body) return { error: "Write a few words about the product." };

  try {
    await fetchWithAuth(`/products/${encodeURIComponent(slug)}/reviews/`, {
      method: "POST",
      body: { rating, title: field(formData, "title"), body },
    });
  } catch (e) {
    if (e instanceof ApiError) {
      if (e.status === 401) {
        return { error: "Your session has expired — please sign in and try again." };
      }
      // The 403 detail ("Only verified purchasers…") IS the explanation; surface it.
      const detail = (e.data as { detail?: unknown } | null)?.detail;
      if (e.status === 403 && typeof detail === "string") return { error: detail };
      return { error: accountErrorMessage(e.status, e.data, FALLBACK) };
    }
    return { error: FALLBACK };
  }

  updateTag(`product:${slug}`);
  return { submitted: true };
}
