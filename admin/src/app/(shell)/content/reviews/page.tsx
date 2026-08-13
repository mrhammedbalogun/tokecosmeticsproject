import type { Metadata } from "next";
import Link from "next/link";
import {
  GoogleReviewsManager,
  type ReviewRow,
  type ReviewsMeta,
} from "@/components/content/GoogleReviewsManager";
import { ApiError } from "@/lib/api";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";

export const metadata: Metadata = { title: "Google reviews" };

const PATH = "/content/reviews";

/** `/content/reviews` — the homepage's featured Google reviews. `marketing.manage`,
 * the banners' scope and reasoning: featured praise is campaign material. */
export default async function GoogleReviewsPage() {
  await requireAdmin(PATH);

  let reviews: ReviewRow[] = [];
  let meta: ReviewsMeta = { rating: null, review_count_text: "", profile_url: "" };
  let error: string | null = null;
  try {
    const [rows, metaData] = await Promise.all([
      fetchWithAuthOrBounce<{ results: ReviewRow[] } | ReviewRow[]>("/admin/google-reviews/", PATH),
      fetchWithAuthOrBounce<ReviewsMeta>("/admin/google-reviews-meta/", PATH),
    ]);
    reviews = Array.isArray(rows) ? rows : (rows?.results ?? []);
    meta = metaData ?? meta;
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    error =
      e.status === 403
        ? "Your role does not include running campaigns."
        : "The reviews could not be loaded.";
  }

  return (
    <div>
      <div>
        <Link href="/content" className="text-sm text-muted hover:text-foreground">
          ← Content
        </Link>
        <h1 className="mt-2 text-lg font-semibold tracking-tight">Google reviews</h1>
        <p className="mt-1 text-sm text-muted">
          The homepage&apos;s &ldquo;Loved on Google&rdquo; section. Each card links to the
          exact review via its Google share-link, so pick the good ones.
        </p>
      </div>
      <div className="mt-6">
        {error ? (
          <p className="rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-4 text-sm text-warn">
            {error}
          </p>
        ) : (
          <GoogleReviewsManager reviews={reviews} meta={meta} />
        )}
      </div>
    </div>
  );
}
