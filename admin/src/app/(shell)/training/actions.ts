"use server";

/**
 * Training-library writes (2026-08-23). `training.manage` — Owner-only — checked by
 * `backend/apps/cms/admin_views.TrainingResourceAdminViewSet` on every request from
 * the database. Nothing here is authorization; a non-Owner who somehow reaches an
 * action gets the 403 rendered back as a sentence.
 */
import { revalidatePath } from "next/cache";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";

const PAGE = "/training";

export interface TrainingActionState {
  savedAt?: number;
  /** Keyed by serializer field name — rendered under the field it names. */
  fieldErrors?: Record<string, string>;
  /** A sentence for the top of the form: an unfielded 400, a 403, a dead API. */
  message?: string | null;
}

export interface TrainingInput {
  /** null = create. */
  id: number | null;
  title: string;
  description: string;
  youtube_url: string;
  position: number;
  is_published: boolean;
}

/** DRF's error bodies come in two shapes — `{field: ["msg"]}` and `{detail: "msg"}` —
 *  and both reach here. Anything unrecognised becomes one honest sentence. */
function toState(e: unknown, fallback: string): TrainingActionState {
  if (!(e instanceof ApiError)) return { message: "The API is not responding." };
  if (e.status === 403) {
    return { message: "Only the Owner can change the training library." };
  }
  const data = (e.data ?? {}) as Record<string, unknown>;
  const fieldErrors: Record<string, string> = {};
  for (const [key, value] of Object.entries(data)) {
    if (key === "detail") continue;
    const first = Array.isArray(value) ? value[0] : value;
    if (typeof first === "string") fieldErrors[key] = first;
  }
  if (Object.keys(fieldErrors).length) return { fieldErrors };
  return { message: typeof data.detail === "string" ? data.detail : fallback };
}

/** Create and update share one action, the stores pattern. PATCH rather than PUT on
 *  update so a field this form does not render can never be blanked by it. */
export async function saveTrainingAction(
  input: TrainingInput,
): Promise<TrainingActionState> {
  // Pre-checks ONLY for a friendlier inline message before the round trip. The
  // serializer re-proves both — including re-parsing the link from scratch.
  if (!input.title.trim()) {
    return {
      fieldErrors: { title: "Give the training a title staff will recognise in the list." },
    };
  }
  if (!input.youtube_url.trim()) {
    return {
      fieldErrors: {
        youtube_url: "Paste the YouTube link of the training video.",
      },
    };
  }

  const body = {
    title: input.title.trim(),
    description: input.description.trim(),
    youtube_url: input.youtube_url.trim(),
    position: input.position,
    is_published: input.is_published,
  };

  try {
    if (input.id === null) {
      await fetchWithAuth("/admin/training/", { method: "POST", body });
    } else {
      await fetchWithAuth(`/admin/training/${input.id}/`, { method: "PATCH", body });
    }
  } catch (e) {
    return toState(e, "That training could not be saved.");
  }
  revalidatePath(PAGE);
  return { savedAt: Date.now() };
}

/**
 * Show or hide one training for staff — a bare `is_published` PATCH carrying nothing
 * else, so flipping a row can never trip the link validation or touch a field the
 * button never rendered.
 */
export async function setTrainingPublishedAction(
  id: number,
  isPublished: boolean,
): Promise<TrainingActionState> {
  try {
    await fetchWithAuth(`/admin/training/${id}/`, {
      method: "PATCH",
      body: { is_published: isPublished },
    });
  } catch (e) {
    return toState(e, "That training could not be updated.");
  }
  revalidatePath(PAGE);
  return { savedAt: Date.now() };
}

/** A REAL delete — unlike stores there is no archive state; "stop showing this but
 *  keep it" is the publish toggle above. The list UI asks twice before calling this. */
export async function deleteTrainingAction(id: number): Promise<TrainingActionState> {
  try {
    await fetchWithAuth(`/admin/training/${id}/`, { method: "DELETE" });
  } catch (e) {
    return toState(e, "That training could not be deleted.");
  }
  revalidatePath(PAGE);
  return { savedAt: Date.now() };
}
