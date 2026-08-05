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

export interface HomepageSection {
  id: number;
  type: string;
  sort: number;
  config: Record<string, unknown>;
}

export interface CmsBanner {
  id: number;
  title: string;
  subtitle: string;
  image: string | null;
  mobile_image: string | null;
  cta_text: string;
  cta_url: string;
  /** Landing redesign: a hero banner may be a video; the image is its poster. */
  video_url: string;
  tagline: string;
  placement: "hero" | "strip" | "category";
  sort: number;
}

export interface GoogleReview {
  id: number;
  author: string;
  location: string;
  rating: number;
  text: string;
  review_url: string;
  reviewed_at_text: string;
  sort: number;
}

export interface HomepagePayload {
  sections: HomepageSection[];
  banners: CmsBanner[];
  reviews?: {
    rating: string | null;
    count_text: string;
    profile_url: string;
    items: GoogleReview[];
  };
}

/**
 * The homepage's CMS content, or nulls when the CMS has nothing to say.
 *
 * ── AN EMPTY CMS MUST NOT BLANK THE HOMEPAGE ────────────────────────────────────────
 *
 * This is a live shop's front door. If the table is empty, the API is down, or somebody
 * deactivates every section, the page falls back to `lib/home-content.ts` — the fixtures
 * Plan-13 shipped, which are what the homepage looks like today. A CMS is a way to change
 * the homepage, not a new way to lose it.
 *
 * Country-aware because banner targeting is: the backend filters on X-Country, so the
 * cache key must vary with it.
 */
export async function getHomepage(country: string): Promise<HomepagePayload | null> {
  try {
    const data = await apiFetch<HomepagePayload>("/cms/homepage/", {
      ...CMS_CACHE,
      country,
    });
    if (!data?.sections?.length && !data?.banners?.length) return null;
    return data;
  } catch {
    return null;
  }
}

/** The announcement strip's messages, falling back to the Plan-13 fixtures. */
export interface AnnouncementItem {
  text: string;
  url: string;
}

export function announcementsFrom(
  payload: HomepagePayload | null,
  fallback: string[],
): AnnouncementItem[] {
  const strips = (payload?.banners ?? [])
    .filter((b) => b.placement === "strip")
    .sort((a, b) => a.sort - b.sort)
    .map((b) => ({ text: b.title, url: b.cta_url }));
  return strips.length ? strips : fallback.map((text) => ({ text, url: "" }));
}
