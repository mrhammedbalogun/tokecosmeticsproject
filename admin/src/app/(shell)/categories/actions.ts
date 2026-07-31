"use server";

/**
 * Editing a category: name, slug, parent, sort order, active.
 *
 * WRITES IMMEDIATELY, like the other separate resources. There is no product form to lose
 * here — the page is a tree and a small form, not a seven-tab editor — so this one DOES
 * `revalidatePath`, and should: reparenting a category changes the tree the page just
 * rendered, and re-reading it is the only way the new shape appears.
 *
 * THE CYCLE CHECK IS THE BACKEND'S. `CategoryAdminSerializer.validate_parent` refuses a
 * parent inside the category's own subtree, because that is where it can see the whole
 * tree and where it protects every caller rather than this one form. The select below
 * hides the obviously-wrong options as a courtesy; the endpoint is the fence.
 */
import { revalidatePath } from "next/cache";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";

export interface CategoryState {
  error?: string;
  fieldErrors?: Record<string, string>;
  saved?: string;
}

const SLUG = /^[-\w]+$/;

function field(formData: FormData, key: string): string {
  const value = formData.get(key);
  return typeof value === "string" ? value.trim() : "";
}

export async function saveCategoryAction(
  _prev: CategoryState,
  formData: FormData,
): Promise<CategoryState> {
  const currentSlug = field(formData, "current_slug");
  if (!SLUG.test(currentSlug)) {
    return { error: "That category could not be identified." };
  }

  const name = field(formData, "name");
  const slug = field(formData, "slug");
  const parentRaw = field(formData, "parent");
  const sortRaw = field(formData, "sort_order");
  const isActive = formData.get("is_active") === "on";

  if (!name) return { fieldErrors: { name: "A category needs a name." } };
  if (!slug) return { fieldErrors: { slug: "A category needs a slug." } };
  if (!SLUG.test(slug)) {
    return { fieldErrors: { slug: "Use letters, numbers, hyphens and underscores only." } };
  }
  if (sortRaw && !/^\d+$/.test(sortRaw)) {
    // `PositiveIntegerField` — the endpoint would refuse a negative or a decimal anyway.
    return { fieldErrors: { sort_order: "Enter a whole number, zero or more." } };
  }

  try {
    await fetchWithAuth(`/admin/categories/${currentSlug}/`, {
      method: "PATCH",
      body: {
        name,
        slug,
        // "" is the select's no-parent option and must become NULL, not be dropped —
        // omitting the key would leave the category where it was, which is the opposite
        // of what "No parent" asks for.
        parent: parentRaw ? Number(parentRaw) : null,
        sort_order: sortRaw ? Number(sortRaw) : 0,
        is_active: isActive,
      },
    });
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    if (e.status === 403) return { error: "Your role does not include managing products." };
    if (e.status === 404) return { error: "That category no longer exists." };
    if (e.status === 400) {
      const data = e.data as Record<string, unknown> | null;
      const fieldErrors: Record<string, string> = {};
      let banner: string | undefined;
      if (data && typeof data === "object") {
        for (const [key, value] of Object.entries(data)) {
          const message = Array.isArray(value) ? value[0] : value;
          if (typeof message !== "string") continue;
          // Includes the cycle refusal, which names both categories and is far more
          // useful than anything this layer could invent.
          if (["name", "slug", "parent", "sort_order"].includes(key)) fieldErrors[key] = message;
          else banner = message;
        }
      }
      if (Object.keys(fieldErrors).length || banner) return { fieldErrors, error: banner };
    }
    return { error: "That category could not be saved." };
  }

  revalidatePath("/categories");
  // The storefront's nav is built from this tree, and the products list shows category
  // membership — both are now stale.
  revalidatePath("/products");
  return { saved: name };
}
