"use server";

/** Customer-review moderation writes (hide / unhide / delete). The words themselves
 * are never editable from here — the backend serializer pins everything but `status`
 * read-only, and this surface offers nothing else. */
import { revalidatePath } from "next/cache";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";

export interface ReviewActionResult {
  error?: string;
}

function fail(e: unknown, fallback: string): ReviewActionResult {
  if (!(e instanceof ApiError)) throw e;
  return {
    error:
      e.status === 403 ? "Your role does not include managing reviews." : fallback,
  };
}

export async function setReviewStatusAction(
  id: number,
  status: "approved" | "hidden",
): Promise<ReviewActionResult> {
  try {
    await fetchWithAuth(`/admin/reviews/${id}/`, { method: "PATCH", body: { status } });
  } catch (e) {
    return fail(e, "The review could not be updated.");
  }
  revalidatePath("/reviews");
  return {};
}

export async function deleteReviewAction(id: number): Promise<ReviewActionResult> {
  try {
    await fetchWithAuth(`/admin/reviews/${id}/`, { method: "DELETE" });
  } catch (e) {
    return fail(e, "The review could not be deleted.");
  }
  revalidatePath("/reviews");
  return {};
}
