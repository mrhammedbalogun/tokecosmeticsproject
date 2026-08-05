import type { Metadata } from "next";
import Link from "next/link";
import { BannerManager } from "@/components/content/BannerManager";
import {
  GoogleReviewsManager,
  type ReviewRow,
  type ReviewsMeta,
} from "@/components/content/GoogleReviewsManager";
import { ApiError } from "@/lib/api";
import type { BannerRow } from "@/lib/banners";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";

export const metadata: Metadata = { title: "Home Content" };

const PATH = "/home-content";

/** `/home-content` — one door for everything the landing page shows, in the order
 * the customer meets it (Hammed's ask: no hunting through Content/Products to
 * change the homepage). Banners and reviews edit HERE; the product rows are
 * collections, so that section explains and links rather than duplicating the
 * product tooling. */

interface CollectionRow {
  id: number;
  name: string;
  slug: string;
  products: number[];
  is_active: boolean;
}

const ROW_COLLECTIONS: { slug: string; section: string }[] = [
  { slug: "best-sellers", section: "“Loved by thousands” row" },
  { slug: "men", section: "New for Men" },
  { slug: "women", section: "For Women" },
  { slug: "babies", section: "For Babies" },
  { slug: "new-arrivals", section: "“Natural Products” row" },
];

export default async function HomeContentPage() {
  await requireAdmin(PATH);

  let banners: BannerRow[] = [];
  let reviews: ReviewRow[] = [];
  let meta: ReviewsMeta = { rating: null, review_count_text: "", profile_url: "" };
  let collections: CollectionRow[] = [];
  let error: string | null = null;
  try {
    const [bannerData, reviewData, metaData, collectionData] = await Promise.all([
      fetchWithAuthOrBounce<{ results: BannerRow[] } | BannerRow[]>("/admin/banners/", PATH),
      fetchWithAuthOrBounce<{ results: ReviewRow[] } | ReviewRow[]>("/admin/google-reviews/", PATH),
      fetchWithAuthOrBounce<ReviewsMeta>("/admin/google-reviews-meta/", PATH),
      // Needs products.manage; a marketer without it still gets the rest of the page.
      fetchWithAuthOrBounce<{ results: CollectionRow[] } | CollectionRow[]>(
        "/admin/collections/",
        PATH,
      ).catch(() => [] as CollectionRow[]),
    ]);
    banners = Array.isArray(bannerData) ? bannerData : (bannerData?.results ?? []);
    reviews = Array.isArray(reviewData) ? reviewData : (reviewData?.results ?? []);
    meta = metaData ?? meta;
    collections = Array.isArray(collectionData) ? collectionData : (collectionData?.results ?? []);
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    error =
      e.status === 403
        ? "Your role does not include editing the homepage."
        : "The homepage content could not be loaded.";
  }

  if (error) {
    return (
      <p className="rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-4 text-sm text-warn">
        {error}
      </p>
    );
  }

  const bySlug = new Map(collections.map((c) => [c.slug, c]));

  return (
    <div className="space-y-10">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Home Content</h1>
        <p className="mt-1 text-sm text-muted">
          Everything the landing page shows, top to bottom. Edits are live on the shop
          within a minute. Sections with no content simply hide on the shop — nothing
          breaks by being empty.
        </p>
      </div>

      <section id="banners">
        <h2 className="text-base font-semibold">1 · Slider &amp; news</h2>
        <p className="mb-4 mt-1 text-sm text-muted">
          <span className="font-medium">Hero</span> banners are the big slider (upload an
          image or a video to each; two or more make it rotate).{" "}
          <span className="font-medium">Announcement strip</span> banners are the scrolling
          news bar. Scheduling applies on the server, so nothing appears early.
        </p>
        <BannerManager banners={banners} />
      </section>

      <section id="rows">
        <h2 className="text-base font-semibold">2 · Product rows</h2>
        <p className="mb-4 mt-1 text-sm text-muted">
          Each row shows a collection. Put products into these collections under{" "}
          <Link href="/products" className="underline underline-offset-2 hover:text-accent">
            Products
          </Link>{" "}
          (product editor → Collections) — a row hides until its collection has products.
        </p>
        <ul className="divide-y divide-line rounded-[var(--radius-card)] border border-line text-sm">
          {ROW_COLLECTIONS.map(({ slug, section }) => {
            const collection = bySlug.get(slug);
            return (
              <li key={slug} className="flex items-center justify-between gap-4 p-3">
                <span>
                  {section}
                  <span className="ml-2 font-mono text-xs text-muted">{slug}</span>
                </span>
                <span className={collection?.products?.length ? "text-ok" : "text-muted"}>
                  {collection
                    ? `${collection.products?.length ?? 0} product${(collection.products?.length ?? 0) === 1 ? "" : "s"}`
                    : "collection not created yet"}
                </span>
              </li>
            );
          })}
        </ul>
      </section>

      <section id="reviews">
        <h2 className="text-base font-semibold">3 · Google reviews</h2>
        <p className="mb-4 mt-1 text-sm text-muted">
          The closing “Loved on Google” section — header numbers plus the featured cards.
        </p>
        <GoogleReviewsManager reviews={reviews} meta={meta} />
      </section>
    </div>
  );
}
