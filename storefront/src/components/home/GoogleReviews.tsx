import type { HomepagePayload } from "@/lib/cms";
import { FadeUp } from "@/components/motion/Motion";

/** The real Google mark, not a hand-drawn letter: content sourced from Google is
 * attributed with Google's own logo, per the Places attribution guidelines. */
function GoogleMark() {
  return (
    <svg
      aria-hidden
      viewBox="0 0 48 48"
      className="absolute right-4 top-4 h-4 w-4"
      focusable="false"
    >
      <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
      <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" />
      <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
    </svg>
  );
}

function Stars({ rating }: { rating: number }) {
  return (
    <span className="tracking-[2px] text-gold" aria-label={`${rating} out of 5 stars`}>
      {"★".repeat(rating)}
      <span className="text-line">{"★".repeat(5 - rating)}</span>
    </span>
  );
}

/** Five is the real-world count (all Google's Places listing ever returns), and it
 * does not divide into a 4-up grid — so widen to 5-up for exactly that case rather
 * than stranding the last card alone. Tailwind needs whole class names, hence the
 * literals. */
function desktopColumns(count: number): string {
  return count === 5 ? "lg:grid-cols-5" : "lg:grid-cols-4";
}

/** Closing section: real Google reviews, curated. Each card links to THAT review's
 * own permalink on Google.
 *
 * Curated rather than synced, re-confirmed 2026-08-17 on terms grounds: Maps
 * Platform Service Specific Terms §14.3 lets us cache latitude/longitude and
 * nothing else from the Places API, so review text can't live in our database if
 * it came from that API. A human transcribes the review and pastes its permalink.
 * The full reasoning (and the sanctioned automation route) is on `cms.GoogleReview`.
 *
 * The header rating/count ARE live — a nightly Place Details call syncs them
 * (`apps/cms/google_reviews.py`), so they can never drift from Google.
 *
 * LAYOUT: 4-up on desktop, but 5-up when there are exactly five — which is what
 * Google's Places listing returns, and what we feature. Without that swap the
 * fifth card orphans onto a row of its own.
 *
 * Renders nothing until at least one review is curated.
 */
export function GoogleReviews({ reviews }: { reviews: HomepagePayload["reviews"] }) {
  if (!reviews || reviews.items.length === 0) return null;
  return (
    <section aria-label="Customer reviews" className="wrap py-16">
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
        <div className={`mt-8 grid gap-4 sm:grid-cols-2 ${desktopColumns(reviews.items.length)}`}>
          {reviews.items.map((review) => (
            <a
              key={review.id}
              href={review.review_url}
              target="_blank"
              rel="noreferrer"
              title="Read this review on Google"
              className="relative block rounded-[var(--radius-card)] border border-line bg-surface p-5 transition-all hover:-translate-y-0.5 hover:shadow-md focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              <GoogleMark />
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
