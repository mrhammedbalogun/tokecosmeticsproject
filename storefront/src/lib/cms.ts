/** CMS content fetchers (Plan-19a). Server-side only.
 *
 * TAGGED AND CACHED, NOT `no-store`. The pages that render this are dynamic — the
 * homepage and shop layout read the country cookie — so Next's route-level ISR does not
 * apply and every cache decision lives here in the data cache. Writing `cache: "no-store"`
 * (the lazy default once `cookies()` is in scope) would send every view of every policy
 * page to the Django VPS.
 *
 * 60 seconds is the plan's stated bar on its own: the master spec's checkpoint asks for a
 * content edit to be "live within a minute". The `cms` tag additionally lets
 * `POST /api/revalidate` flush it instantly once a backend notifier exists — the storefront
 * half of that has been built since Plan-13 (`app/api/revalidate/route.ts`); the Django
 * caller has not.
 */
import { apiFetch, ApiError } from "@/lib/api";

export interface CmsPage {
  title: string;
  slug: string;
  body: string;
  seo_title: string;
  seo_description: string;
  updated_at: string;
}

const CMS_CACHE = { next: { revalidate: 60, tags: ["cms"] } };

/** One published page, or null when it does not exist or is still a draft. The backend
 *  answers 404 for both, deliberately — see `PublicPageDetailView`. */
export async function getPage(slug: string): Promise<CmsPage | null> {
  try {
    return await apiFetch<CmsPage>(`/cms/pages/${encodeURIComponent(slug)}/`, CMS_CACHE);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null;
    throw e;
  }
}

/** Every published page, for `sitemap.ts`. Unpaginated by design — there are eleven. */
export async function getPages(): Promise<CmsPage[]> {
  return apiFetch<CmsPage[]>("/cms/pages/", CMS_CACHE);
}
