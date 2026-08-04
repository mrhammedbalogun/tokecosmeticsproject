import type { HomepagePayload } from "@/lib/cms";
import { FadeUp } from "@/components/motion/Motion";

/** Closing section (approved 2026-08-04): curated Google reviews. Each card links
 * to THAT review's Google permalink (the admin pastes the share-link — the Places
 * API has no per-review URL, which is why these are curated, not synced). The
 * header numbers are admin-entered and can later be fed by a Places fetch.
 * Renders nothing until at least one review is curated.
 */
function Stars({ rating }: { rating: number }) {
  return (
    <span className="tracking-[2px] text-gold" aria-label={`${rating} out of 5 stars`}>
      {"★".repeat(rating)}
      <span className="text-line">{"★".repeat(5 - rating)}</span>
    </span>
  );
}

export function GoogleReviews({ reviews }: { reviews: HomepagePayload["reviews"] }) {
  if (!reviews || reviews.items.length === 0) return null;
  return (
    <section aria-label="Customer reviews" className="mx-auto max-w-7xl px-4 py-16">
      <FadeUp>
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.18em] text-muted">
              Customer Reviews
            </p>
            <h2 className="mt-1 font-display text-3xl md:text-4xl">Loved on Google</h2>
            {reviews.rating && (
              <p className="mt-2 flex items-center gap-2.5 text-sm text-muted">
                <span className="font-display text-xl text-foreground">{reviews.rating}</span>
                <Stars rating={Math.round(Number(reviews.rating))} />
                {reviews.count_text && <span>from {reviews.count_text} Google reviews</span>}
              </p>
            )}
          </div>
          {reviews.profile_url && (
            <a
              href={reviews.profile_url}
              target="_blank"
              rel="noreferrer"
              className="rounded-full border border-line px-6 py-2.5 text-sm font-medium transition-colors hover:border-accent hover:text-accent"
            >
              Review us on Google
            </a>
          )}
        </div>
        <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {reviews.items.map((review) => (
            <a
              key={review.id}
              href={review.review_url}
              target="_blank"
              rel="noreferrer"
              title="Read this review on Google"
              className="relative block rounded-[var(--radius-card)] border border-line bg-surface p-5 transition-all hover:-translate-y-0.5 hover:shadow-md focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              <span
                aria-hidden
                className="absolute right-4 top-4 grid h-5 w-5 place-items-center rounded-full border border-line bg-surface text-[11px] font-bold text-[#4285f4]"
              >
                G
              </span>
              <Stars rating={review.rating} />
              <p className="mt-2.5 line-clamp-4 text-sm leading-relaxed">{review.text}</p>
              <p className="mt-3.5 text-xs">
                <span className="font-semibold">{review.author}</span>
                <span className="text-muted">
                  {review.reviewed_at_text && ` · ${review.reviewed_at_text}`}
                  {review.location && ` · ${review.location}`}
                </span>
              </p>
            </a>
          ))}
        </div>
      </FadeUp>
    </section>
  );
}
