/** Legacy WordPress URL lookups (Plan-24). Server-side only.
 *
 * Called ONLY by the root catch-all, which Next reaches only when no real route matched.
 * That ordering is the whole design: WordPress served pages, posts and help articles from
 * the root, and three of those slugs are live storefront routes today — `/account` was a
 * help article, `/search` and `/checkout` were pages. Looking redirects up in middleware
 * instead would need a hand-maintained list of paths to skip, and the day somebody forgets
 * to add a new route to it is the day a signed-in customer gets bounced off their own
 * account page.
 *
 * Cached hard: the table changes at migration time and essentially never afterwards, and
 * the backend already caches the lookup too. The `redirects` tag lets
 * `POST /api/revalidate` flush it when an admin edits a row.
 */
import { apiFetch, ApiError } from "@/lib/api";

export interface RedirectRule {
  old_path: string;
  new_path: string;
  status_code: number;
}

/** The rule for a path, or null for a genuine 404.
 *
 * A backend failure returns null rather than throwing: if the API is down, the visitor
 * should get the 404 page, not a 500. They were heading for a 404 anyway — this lookup is
 * a chance to do better, never a reason to do worse.
 */
export async function getRedirect(path: string): Promise<RedirectRule | null> {
  try {
    return await apiFetch<RedirectRule>(
      `/meta/redirect/?path=${encodeURIComponent(path)}`,
      { next: { revalidate: 3600, tags: ["redirects"] } },
    );
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null;
    return null;
  }
}
