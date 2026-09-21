"use server";

/**
 * Careers writes (Plan-45). Two scopes, two groups of action, and nothing here is
 * authorization — `apps/careers/admin_views.py` re-checks every one on every request,
 * from the database. These are ergonomics around it.
 *
 * ── WHY THE TWO GROUPS SHARE A FILE ─────────────────────────────────────────────────
 *
 * They are one screen to the person using it: you open Careers, you post a role, you
 * read who applied. Splitting the file would follow the scope boundary rather than the
 * task, and the scope boundary is already enforced where it matters.
 */
import { revalidatePath } from "next/cache";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";
import type { ApplicationStatus, JobLocationRow, JobRow } from "@/lib/careers";

const JOBS_PAGE = "/careers";
const APPLICATIONS_PAGE = "/careers/applications";

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
  if (error.status === 403) {
    return { message: "Your role does not include this." };
  }
  const data = (error.data ?? {}) as Record<string, unknown>;
  if (typeof data.detail === "string") return { message: data.detail };

  const fieldErrors: Record<string, string> = {};
  for (const [field, value] of Object.entries(data)) {
    const first = Array.isArray(value) ? value[0] : value;
    if (typeof first === "string") fieldErrors[field] = first;
    // Nested location errors arrive as an array of per-row objects; surfacing the first
    // real message is enough for a field that is edited as a list.
    if (Array.isArray(value) && typeof first === "object" && first !== null) {
      const nested = Object.values(first as Record<string, unknown>)[0];
      const text = Array.isArray(nested) ? nested[0] : nested;
      if (typeof text === "string") fieldErrors[field] = text;
    }
  }
  if (Object.keys(fieldErrors).length > 0) {
    return { fieldErrors, message: "Check the highlighted fields." };
  }
  return { message: fallback };
}

export interface JobInput {
  slug: string | null;
  title: string;
  department: string;
  employment_type: string;
  workplace_type: string;
  country: string;
  compensation_text: string;
  summary: string;
  description: string;
  requirements: string;
  status: string;
  closes_at: string | null;
  sort_order: number;
  locations: JobLocationRow[];
}

export async function saveJob(input: JobInput): Promise<ActionState> {
  const body = {
    title: input.title,
    department: input.department,
    employment_type: input.employment_type,
    workplace_type: input.workplace_type,
    country: input.country,
    compensation_text: input.compensation_text,
    summary: input.summary,
    description: input.description,
    requirements: input.requirements,
    status: input.status,
    // An empty datetime-local field must clear the deadline, not send "".
    closes_at: input.closes_at || null,
    sort_order: input.sort_order,
    locations: input.locations
      .filter((row) => row.label.trim())
      .map((row, index) => ({
        ...(row.id ? { id: row.id } : {}),
        label: row.label.trim(),
        sort_order: index,
      })),
  };
  try {
    await fetchWithAuth<JobRow>(
      input.slug ? `/admin/careers/jobs/${input.slug}/` : "/admin/careers/jobs/",
      { method: input.slug ? "PATCH" : "POST", body },
    );
  } catch (error) {
    return toState(error, "That role could not be saved.");
  }
  revalidatePath(JOBS_PAGE);
  return { savedAt: Date.now() };
}

/** Archive. NOT a delete — applications point at the posting with PROTECT, so removing
 *  one would mean removing the people who applied to it. */
export async function archiveJob(slug: string): Promise<ActionState> {
  try {
    await fetchWithAuth(`/admin/careers/jobs/${slug}/`, { method: "DELETE" });
  } catch (error) {
    return toState(error, "That role could not be archived.");
  }
  revalidatePath(JOBS_PAGE);
  return { savedAt: Date.now() };
}

/** Restores AS A DRAFT, by the backend's choice — see its docstring. The button says so,
 *  because a restore that silently republishes a filled job to the public careers page
 *  is a surprise nobody wants twice. */
export async function restoreJob(slug: string): Promise<ActionState> {
  try {
    await fetchWithAuth(`/admin/careers/jobs/${slug}/restore/`, { method: "POST" });
  } catch (error) {
    return toState(error, "That role could not be restored.");
  }
  revalidatePath(JOBS_PAGE);
  return { savedAt: Date.now() };
}

export async function updateApplication(
  id: number,
  patch: { status?: ApplicationStatus; staff_notes?: string },
): Promise<ActionState> {
  try {
    await fetchWithAuth(`/admin/careers/applications/${id}/`, {
      method: "PATCH",
      body: patch,
    });
  } catch (error) {
    return toState(error, "That application could not be updated.");
  }
  revalidatePath(APPLICATIONS_PAGE);
  revalidatePath(`${APPLICATIONS_PAGE}/${id}`);
  return { savedAt: Date.now() };
}

/**
 * PERMANENT, and it takes the CV with it. Owner-only at the API.
 *
 * This is what "please delete my application" resolves to, which is why it exists at
 * all and why nothing auto-purges: a hiring record disappearing on a timer is worse
 * than one kept until somebody decides otherwise.
 */
export async function deleteApplication(id: number): Promise<ActionState> {
  try {
    await fetchWithAuth(`/admin/careers/applications/${id}/`, { method: "DELETE" });
  } catch (error) {
    return toState(
      error,
      "That application could not be deleted.",
    );
  }
  revalidatePath(APPLICATIONS_PAGE);
  return { savedAt: Date.now() };
}

/**
 * Fetch a short-lived link to one CV.
 *
 * A SERVER ACTION rather than a client fetch, because the browser has no admin token —
 * the access cookie is httpOnly. The action returns the presigned URL (or, in dev, the
 * path of the streaming endpoint) and the client opens it. The URL lives sixty seconds.
 */
export async function resumeLink(
  id: number,
  disposition: "inline" | "attachment",
): Promise<{ url?: string; filename?: string; message?: string }> {
  try {
    const result = await fetchWithAuth<{ url: string; filename: string }>(
      `/admin/careers/applications/${id}/resume/?disposition=${disposition}`,
    );
    return result;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      return { message: "This application has no CV attached." };
    }
    if (error instanceof ApiError && error.status === 403) {
      return { message: "Your role does not include opening CVs." };
    }
    return { message: "That CV could not be opened. Try again." };
  }
}
