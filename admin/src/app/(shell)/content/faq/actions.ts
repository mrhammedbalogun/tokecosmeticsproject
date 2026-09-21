"use server";

/** Writes for the FAQ admin screen.
 *
 * `answer` is NEVER sent. It is read-only on the serializer and derived from
 * `answer_source` by the sanitiser in `FaqItem.save()` — the same property the pages
 * editor relies on, and the only route to storefront-rendered HTML runs through the
 * allow-list.
 */
import { revalidatePath } from "next/cache";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";

export interface FaqSaveState {
  savedAt?: number;
  fieldErrors?: Record<string, string>;
  message?: string | null;
}

const PATH = "/content/faq";

function parseErrors(e: unknown, fields: string[], fallback: string): FaqSaveState {
  if (!(e instanceof ApiError)) return { message: "The API is not responding." };
  const data = e.data as Record<string, unknown> | undefined;
  const fieldErrors: Record<string, string> = {};
  for (const key of fields) {
    const value = data?.[key];
    const first = Array.isArray(value) ? value[0] : value;
    if (typeof first === "string") fieldErrors[key] = first;
  }
  return Object.keys(fieldErrors).length ? { fieldErrors } : { message: fallback };
}

export async function saveFaqItemAction(input: {
  id: number;
  question: string;
  answer_source: string;
  sort: number;
  is_published: boolean;
}): Promise<FaqSaveState> {
  const question = input.question.trim();
  if (!question) return { fieldErrors: { question: "A question needs some words." } };
  // Publishing an empty answer would put a blank accordion panel in front of a customer.
  if (input.is_published && !input.answer_source.trim()) {
    return { fieldErrors: { answer_source: "Write the answer before publishing it." } };
  }
  try {
    await fetchWithAuth(`/admin/faq-items/${input.id}/`, {
      method: "PATCH",
      body: {
        question,
        answer_source: input.answer_source,
        sort: input.sort,
        is_published: input.is_published,
      },
    });
  } catch (e) {
    return parseErrors(e, ["question", "answer_source", "sort"], "That answer could not be saved.");
  }
  revalidatePath(PATH);
  return { savedAt: Date.now() };
}

export async function createFaqItemAction(input: {
  category: number;
  question: string;
  answer_source: string;
}): Promise<FaqSaveState> {
  const question = input.question.trim();
  if (!question) return { fieldErrors: { question: "A question needs some words." } };
  try {
    await fetchWithAuth("/admin/faq-items/", {
      method: "POST",
      body: {
        category: input.category,
        question,
        answer_source: input.answer_source,
        // BORN UNPUBLISHED, always. A new question reaches the shop only when somebody
        // has read the answer back and pressed publish.
        is_published: false,
      },
    });
  } catch (e) {
    return parseErrors(e, ["question", "answer_source", "category"],
                       "That question could not be added.");
  }
  revalidatePath(PATH);
  return { savedAt: Date.now() };
}

export async function deleteFaqItemAction(id: number): Promise<FaqSaveState> {
  try {
    await fetchWithAuth(`/admin/faq-items/${id}/`, { method: "DELETE" });
  } catch (e) {
    return parseErrors(e, [], "That question could not be removed.");
  }
  revalidatePath(PATH);
  return { savedAt: Date.now() };
}

export async function saveFaqCategoryAction(input: {
  id: number;
  name: string;
  blurb: string;
  sort: number;
  is_active: boolean;
}): Promise<FaqSaveState> {
  const name = input.name.trim();
  if (!name) return { fieldErrors: { name: "A category needs a name." } };
  try {
    await fetchWithAuth(`/admin/faq-categories/${input.id}/`, {
      method: "PATCH",
      body: { name, blurb: input.blurb.trim(), sort: input.sort, is_active: input.is_active },
    });
  } catch (e) {
    return parseErrors(e, ["name", "blurb", "sort"], "That category could not be saved.");
  }
  revalidatePath(PATH);
  return { savedAt: Date.now() };
}

export async function createFaqCategoryAction(input: { name: string }): Promise<FaqSaveState> {
  const name = input.name.trim();
  if (!name) return { fieldErrors: { name: "A category needs a name." } };
  try {
    await fetchWithAuth("/admin/faq-categories/", { method: "POST", body: { name } });
  } catch (e) {
    return parseErrors(e, ["name"], "That category could not be created.");
  }
  revalidatePath(PATH);
  return { savedAt: Date.now() };
}
