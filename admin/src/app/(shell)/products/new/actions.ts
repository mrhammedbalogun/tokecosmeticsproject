"use server";

/**
 * Creating a product.
 *
 * ── MINIMUM VIABLE RECORD, THEN THE EDITOR ──────────────────────────────────────────
 *
 * Name and slug, and nothing else. Asking for seven tabs' worth of detail before the first
 * save means a half-filled form that cannot be put down — and every one of those fields is
 * editable a second later on a page built for exactly that.
 *
 * IT IS CREATED AS A DRAFT, by omission rather than by sending `status`. `Product.status`
 * defaults to `"draft"` in the model, and a product created straight to `active` would be
 * one with no price, no image and no copy. The Details tab publishes it when it is ready.
 *
 * NO CLIENT-SIDE UNIQUENESS CHECK, ANYWHERE. `Product.slug` is `unique=True`; only the
 * database knows whether a slug is free, and a browser-side check that disagreed with it
 * would be worse than none — it would refuse slugs that are available and admit ones that
 * are not. The backend's own message is surfaced verbatim, per the 17a spec.
 */
import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";
import { ApiError } from "@/lib/api";
import { isSlugShaped, slugify } from "@/lib/slugify";
import { fetchWithAuth } from "@/lib/session";

export interface CreateState {
  error?: string;
  fieldErrors?: { name?: string; slug?: string };
  /** Echoed back so a rejected form re-renders with what was typed. */
  values?: { name: string; slug: string };
}

function field(formData: FormData, key: string): string {
  const value = formData.get(key);
  return typeof value === "string" ? value.trim() : "";
}

export async function createProductAction(
  _prev: CreateState,
  formData: FormData,
): Promise<CreateState> {
  const name = field(formData, "name");
  // An empty slug is filled from the name rather than refused: the field is a convenience,
  // and somebody who cleared it meant "you choose", not "fail".
  const slug = field(formData, "slug") || slugify(name);
  const values = { name, slug };

  if (!name) return { fieldErrors: { name: "A product needs a name." }, values };
  if (!slug) {
    // Reachable: a name of only punctuation slugifies to "".
    return {
      fieldErrors: { slug: "Enter a slug — the name did not produce one." },
      values,
    };
  }
  if (!isSlugShaped(slug)) {
    return {
      fieldErrors: { slug: "Use letters, numbers, hyphens and underscores only." },
      values,
    };
  }

  let created: { slug: string };
  try {
    created = await fetchWithAuth<{ slug: string }>("/admin/products/", {
      method: "POST",
      body: { name, slug },
    });
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    if (e.status === 403) {
      return { error: "Your role does not include managing products.", values };
    }
    if (e.status === 400) {
      const data = e.data as Record<string, unknown> | null;
      const fieldErrors: { name?: string; slug?: string } = {};
      let banner: string | undefined;
      if (data && typeof data === "object") {
        for (const [key, value] of Object.entries(data)) {
          const message = Array.isArray(value) ? value[0] : value;
          if (typeof message !== "string") continue;
          // Surfaced VERBATIM. "product with this slug already exists." is the backend's
          // own sentence and it is both accurate and specific; replacing it with our own
          // wording would be a second place for that rule to be described.
          if (key === "name" || key === "slug") fieldErrors[key] = message;
          else banner = message;
        }
      }
      if (Object.keys(fieldErrors).length || banner) {
        return { fieldErrors, error: banner, values };
      }
    }
    return { error: "The product could not be created.", values };
  }

  revalidatePath("/products");
  // OUTSIDE the try/catch: `redirect` works by throwing NEXT_REDIRECT, and a catch block
  // around it would swallow the navigation and report a failed create that succeeded.
  redirect(`/products/${created.slug}`);
}
