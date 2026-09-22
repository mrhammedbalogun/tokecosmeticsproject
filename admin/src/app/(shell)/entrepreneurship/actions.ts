"use server";

/**
 * Programme writes. Nothing here is authorization — `apps/entrepreneurship/admin_views.py`
 * re-checks every one on every request, from the database. These are ergonomics around
 * it, and the sentences a refusal turns into.
 */
import { revalidatePath } from "next/cache";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";
import type { ApplicationStatus, ProgrammeSettings } from "@/lib/entrepreneurship";

const LIST_PAGE = "/entrepreneurship";

export interface ActionState {
  savedAt?: number;
  /** Keyed by serializer field name — rendered under the field it names. */
  fieldErrors?: Record<string, string>;
  /** A sentence for the top of the form: an unfielded 400, a 403, a dead API. */
  message?: string | null;
}

/** DRF's error bodies come in two shapes — `{field: ["msg"]}` and `{detail: "msg"}` —
 *  and both reach here. Anything unrecognised becomes one honest sentence rather than a
 *  JSON blob rendered at an operator. */
function toState(error: unknown, fallback: string): ActionState {
  if (!(error instanceof ApiError)) return { message: "The API is not responding." };
  if (error.status === 403) return { message: "Your role does not include this." };

  const data = (error.data ?? {}) as Record<string, unknown>;
  if (typeof data.detail === "string") return { message: data.detail };

  const fieldErrors: Record<string, string> = {};
  for (const [field, value] of Object.entries(data)) {
    const first = Array.isArray(value) ? value[0] : value;
    if (typeof first === "string") fieldErrors[field] = first;
  }
  if (Object.keys(fieldErrors).length > 0) {
    return { fieldErrors, message: "Check the highlighted fields." };
  }
  return { message: fallback };
}

/**
 * Open or close the intake.
 *
 * THE ONE WRITE ON THIS SCREEN THAT CHANGES THE PUBLIC SITE. Django fires a storefront
 * revalidation on save (`apps/entrepreneurship/revalidate.py`), so the form comes off
 * tokecosmetics.com within a second rather than at the end of the cache window — which
 * is the entire reason this is a database row and not a deploy.
 */
export async function saveProgrammeSettings(input: {
  is_open: boolean;
  closed_message: string;
}): Promise<ActionState> {
  try {
    await fetchWithAuth<ProgrammeSettings>("/admin/entrepreneurship/settings/", {
      method: "PATCH",
      body: { is_open: input.is_open, closed_message: input.closed_message },
    });
  } catch (error) {
    return toState(error, "That could not be saved.");
  }
  revalidatePath(LIST_PAGE);
  return { savedAt: Date.now() };
}

export async function updateApplication(
  id: number,
  patch: { status?: ApplicationStatus; staff_notes?: string },
): Promise<ActionState> {
  try {
    await fetchWithAuth(`/admin/entrepreneurship/applications/${id}/`, {
      method: "PATCH",
      body: patch,
    });
  } catch (error) {
    return toState(error, "That application could not be updated.");
  }
  revalidatePath(LIST_PAGE);
  revalidatePath(`${LIST_PAGE}/${id}`);
  return { savedAt: Date.now() };
}

/**
 * PERMANENT. Owner-only at the API.
 *
 * This is what "please delete my details" resolves to, which is why it exists at all and
 * why nothing auto-purges: a record disappearing on a timer is worse than one kept until
 * somebody decides otherwise.
 */
export async function deleteApplication(id: number): Promise<ActionState> {
  try {
    await fetchWithAuth(`/admin/entrepreneurship/applications/${id}/`, {
      method: "DELETE",
    });
  } catch (error) {
    return toState(error, "That application could not be deleted.");
  }
  revalidatePath(LIST_PAGE);
  return { savedAt: Date.now() };
}
