import { apiFetch } from "@/lib/api";

/** One question and its SANITISED answer. `answer_source` is deliberately absent from
 *  the public payload — see `PublicFaqItemSerializer`. */
export interface FaqItem {
  id: number;
  question: string;
  answer: string;
}

export interface FaqCategory {
  name: string;
  slug: string;
  blurb: string;
  items: FaqItem[];
}

/**
 * The whole FAQ in one request.
 *
 * Same `cms` tag as pages and banners, so an answer edited in the admin flushes the
 * storefront immediately rather than within the TTL — the point being that a wrong
 * answer about refunds is corrected BECAUSE it is wrong, which is the one moment
 * "within a minute" is not good enough.
 *
 * The backend omits any category with nothing published in it, so this never returns a
 * heading with an empty list under it.
 */
export async function getFaq(): Promise<FaqCategory[]> {
  try {
    return await apiFetch<FaqCategory[]>("/cms/faq/", {
      next: { revalidate: 60, tags: ["cms"] },
    });
  } catch {
    // An FAQ that cannot load must not take the page down with it; the route renders
    // its contact fallback instead.
    return [];
  }
}
