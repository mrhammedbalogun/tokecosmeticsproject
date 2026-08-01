"use server";

/** Writes for the CMS pages admin (Plan-19a).
 *
 * `body` is never sent: it is read-only on the serializer and derived from `body_source`
 * by the sanitiser in `Page.save()`. That is the whole security property — the only route
 * to storefront-rendered HTML runs through the allow-list.
 */
import { revalidatePath } from "next/cache";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";

export interface PageSaveState {
  savedAt?: number;
  fieldErrors?: Record<string, string>;
  message?: string | null;
  /** The slug the page now has — it may have been edited. */
  slug?: string;
}

const SLUG = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

function parseErrors(e: unknown): PageSaveState | null {
  if (!(e instanceof ApiError)) return { message: "The API is not responding." };
  const data = e.data as Record<string, unknown> | undefined;
  const fieldErrors: Record<string, string> = {};
  for (const key of ["title", "slug", "body_source", "status", "seo_title", "seo_description"]) {
    const value = data?.[key];
    const first = Array.isArray(value) ? value[0] : value;
    if (typeof first === "string") fieldErrors[key] = first;
  }
  if (Object.keys(fieldErrors).length) return { fieldErrors };
  return { message: "That page could not be saved." };
}

export async function savePageAction(input: {
  currentSlug: string;
  title: string;
  slug: string;
  body_source: string;
  status: "draft" | "published";
  seo_title: string;
  seo_description: string;
}): Promise<PageSaveState> {
  const title = input.title.trim();
  const slug = input.slug.trim().toLowerCase();
  if (!title) return { fieldErrors: { title: "A page needs a title." } };
  // The slug is a published URL the footer hard-codes, so a malformed one is refused
  // here rather than becoming a link nobody can reach.
  if (!SLUG.test(slug)) {
    return { fieldErrors: { slug: "Lower-case letters, numbers and hyphens only." } };
  }

  try {
    await fetchWithAuth(`/admin/pages/${encodeURIComponent(input.currentSlug)}/`, {
      method: "PATCH",
      body: {
        title,
        slug,
        body_source: input.body_source,
        status: input.status,
        seo_title: input.seo_title.trim(),
        seo_description: input.seo_description.trim(),
      },
    });
  } catch (e) {
    return parseErrors(e) ?? { message: "That page could not be saved." };
  }

  revalidatePath("/content");
  revalidatePath(`/content/${slug}`);
  return { savedAt: Date.now(), slug };
}

export async function createPageAction(input: {
  title: string;
  slug: string;
}): Promise<PageSaveState> {
  const title = input.title.trim();
  const slug = input.slug.trim().toLowerCase();
  if (!title) return { fieldErrors: { title: "A page needs a title." } };
  if (!SLUG.test(slug)) {
    return { fieldErrors: { slug: "Lower-case letters, numbers and hyphens only." } };
  }

  try {
    await fetchWithAuth("/admin/pages/", {
      method: "POST",
      body: { title, slug, body_source: "", status: "draft" },
    });
  } catch (e) {
    return parseErrors(e) ?? { message: "That page could not be created." };
  }

  revalidatePath("/content");
  return { savedAt: Date.now(), slug };
}
