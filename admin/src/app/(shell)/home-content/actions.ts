"use server";

/** The homepage product rows' collection choices (Phase 3, 2026-08-06).
 *
 * A row's choice is one `HomepageSection` of type `collection_carousel` with
 * `config: {row, collection}` — the storefront reads it in `lib/cms.ts#rowCollection`
 * and falls back to the built-in slug when the section is absent. `marketing.manage`,
 * like the banners: the homepage is the campaign.
 */
import { revalidatePath } from "next/cache";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";

export type RowKey = "loved" | "natural";

export interface RowState {
  savedAt?: number;
  message?: string | null;
}

export async function saveRowCollectionAction(input: {
  /** The existing section's id, when the row already has a choice saved. */
  sectionId: number | null;
  row: RowKey;
  /** null = back to the built-in collection (the section is deleted). */
  collection: string | null;
}): Promise<RowState> {
  try {
    if (!input.collection) {
      if (input.sectionId) {
        await fetchWithAuth(`/admin/homepage-sections/${input.sectionId}/`, { method: "DELETE" });
      }
    } else if (input.sectionId) {
      await fetchWithAuth(`/admin/homepage-sections/${input.sectionId}/`, {
        method: "PATCH",
        body: { config: { row: input.row, collection: input.collection } },
      });
    } else {
      await fetchWithAuth("/admin/homepage-sections/", {
        method: "POST",
        body: {
          type: "collection_carousel",
          // Mirrors the row's position on the page (section 6 and 10) — cosmetic only,
          // the storefront finds rows by config.row, not by sort.
          sort: input.row === "loved" ? 6 : 10,
          config: { row: input.row, collection: input.collection },
          is_active: true,
        },
      });
    }
  } catch (e) {
    if (!(e instanceof ApiError)) return { message: "The API is not responding." };
    return { message: "That choice could not be saved." };
  }
  revalidatePath("/home-content");
  return { savedAt: Date.now() };
}
