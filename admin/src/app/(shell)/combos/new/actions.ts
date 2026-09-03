"use server";

/**
 * Creating a combo: a name, a slug, and nothing else.
 *
 * MINIMUM VIABLE RECORD, THEN THE BUILDER — the same shape as `products/new`, and for the
 * same reason: asking for the contents, the markets and four prices before the first save
 * means a half-filled form that cannot be put down, and every one of those is editable a
 * second later on a screen built for exactly that.
 *
 * IT IS CREATED AS A DRAFT, by omission rather than by sending `status`. `Combo.status`
 * defaults to `"draft"`, and a combo created straight to active would be one with an
 * empty box — which `available_in` would refuse to sell anyway, silently.
 *
 * NO CLIENT-SIDE UNIQUENESS CHECK. `Combo.slug` is `unique=True`; only the database knows
 * whether a slug is free, and a browser-side check that disagreed would be worse than
 * none. The backend's own message is surfaced verbatim.
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

export async function createComboAction(
  _prev: CreateState,
  formData: FormData,
): Promise<CreateState> {
  const name = field(formData, "name");
  // An empty slug is filled from the name rather than refused: the field is a
  // convenience, and somebody who cleared it meant "you choose", not "fail".
  const slug = field(formData, "slug") || slugify(name);
  const values = { name, slug };

  if (!name) return { fieldErrors: { name: "A combo needs a name." }, values };
  if (!slug) {
    // Reachable: a name of only punctuation slugifies to "".
    return { fieldErrors: { slug: "Enter a slug — the name did not produce one." }, values };
  }
  if (!isSlugShaped(slug)) {
    return {
      fieldErrors: { slug: "Use letters, numbers, hyphens and underscores only." },
      values,
    };
  }

  try {
    await fetchWithAuth("/admin/combos/", { method: "POST", body: { name, slug } });
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    const data = (e.data ?? {}) as Record<string, unknown>;
    const first = (key: string) => {
      const v = data[key];
      return Array.isArray(v) ? String(v[0]) : v ? String(v) : undefined;
    };
    if (e.status === 403) {
      return { error: "Your role does not include managing products.", values };
    }
    const fieldErrors = { name: first("name"), slug: first("slug") };
    if (fieldErrors.name || fieldErrors.slug) return { fieldErrors, values };
    return { error: first("detail") ?? "The combo could not be created.", values };
  }

  revalidatePath("/combos");
  // Straight into the builder — creating a combo and then hunting for it in a list is a
  // step that exists only because somebody forgot to remove it.
  redirect(`/combos/${slug}`);
}
