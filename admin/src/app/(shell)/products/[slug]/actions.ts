"use server";

/**
 * The product editor's save.
 *
 * A SERVER FUNCTION, like every other authenticated write in this app: it gets Next's
 * Origin/Host check for free and it may persist a rotated token, which a Server Component
 * may not. So `fetchWithAuth` — the renewing fetcher — is correct here, and would be wrong
 * on the page.
 *
 * ONE PATCH FOR THE PRODUCT'S OWN FIELDS (17a design decision 1). Variants, prices, images
 * and stock are separate resources with their own writes; they are not part of this.
 *
 * THE SLUG CAN CHANGE, and that makes this the one write in the app whose success may
 * invalidate the URL the caller is sitting on. The returned `slug` is what actually
 * landed, and the client navigates to it — reading the response rather than assuming the
 * submitted value took, because the backend may normalise it.
 *
 * VALIDATION HERE IS NOT THE CONTROL. A Server Function is a public POST endpoint. Django
 * validates every field and gates the whole call on `HasAdminScope("products.manage")`.
 * What the checks below buy is a legible message instead of a 400 rendered as "something
 * went wrong", and a slug that cannot be used to address a path nobody wrote.
 */
import { revalidatePath } from "next/cache";
import { ApiError } from "@/lib/api";
import {
  isProductStatus,
  parseFieldErrors,
  type FieldErrors,
  type ProductFormValues,
} from "@/lib/product-form";
import { fetchWithAuth } from "@/lib/session";

export interface SaveState {
  /** Set on success — the slug the product now has, which may differ from the old one. */
  savedSlug?: string;
  savedAt?: number;
  errors?: FieldErrors;
}

/** A slug is interpolated into the request PATH, so its shape is checked before it gets
 *  there. Django's SlugField accepts letters, numbers, hyphens and underscores. */
const SLUG = /^[-\w]+$/;

export async function saveProductAction(
  currentSlug: string,
  values: ProductFormValues,
): Promise<SaveState> {
  if (!SLUG.test(currentSlug)) {
    return { errors: { fields: {}, banner: "That product could not be identified." } };
  }

  const name = values.name.trim();
  const slug = values.slug.trim();

  // Cheap, legible refusals for the two that would otherwise come back as a bare 400.
  if (!name) return { errors: { fields: { name: "A product needs a name." } } };
  if (!slug) return { errors: { fields: { slug: "A product needs a slug." } } };
  if (!SLUG.test(slug)) {
    return {
      errors: {
        fields: { slug: "Use letters, numbers, hyphens and underscores only." },
      },
    };
  }
  if (!isProductStatus(values.status)) {
    return { errors: { fields: { status: `${values.status} is not a status.` } } };
  }

  let saved: { slug: string };
  try {
    saved = await fetchWithAuth<{ slug: string }>(`/admin/products/${currentSlug}/`, {
      method: "PATCH",
      body: {
        name,
        slug,
        status: values.status,
        short_description: values.short_description,
        description: values.description,
        is_featured: values.is_featured,
        categories: values.categories,
        tags: values.tags,
        available_countries: values.available_countries,
      },
    });
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    if (e.status === 403) {
      return {
        errors: { fields: {}, banner: "Your role does not include managing products." },
      };
    }
    if (e.status === 404) {
      return { errors: { fields: {}, banner: "That product no longer exists." } };
    }
    if (e.status === 400) {
      const errors = parseFieldErrors(e.data);
      // A 400 with nothing attributable still needs to say something. Silence here reads
      // as "the save worked" to anybody not watching the network tab.
      if (!Object.keys(errors.fields).length && !errors.banner) {
        errors.banner = "The changes were rejected.";
      }
      return { errors };
    }
    return { errors: { fields: {}, banner: "The changes could not be saved." } };
  }

  // Both paths: the old URL's cache entry is stale whether or not the slug moved.
  revalidatePath(`/products/${currentSlug}`);
  if (saved.slug !== currentSlug) revalidatePath(`/products/${saved.slug}`);
  revalidatePath("/products");

  return { savedSlug: saved.slug, savedAt: Date.now() };
}
