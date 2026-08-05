import { getReviews } from "@/lib/catalog";
import { ReviewStars } from "@/components/product/ReviewStars";
import { ReviewForm } from "@/components/product/ReviewForm";
import { submitReviewAction } from "@/app/(shop)/product/[slug]/actions";

/** Approved reviews plus the write-a-review states. Every listed review is a
 * verified purchase by backend construction (only verified purchasers can post),
 * so the badge is unconditional. The section always renders — a product with no
 * reviews yet is exactly where the "be the first" CTA matters. `id="reviews"` is
 * the BuyBox stars' jump target; scroll-mt clears the sticky header. */
export async function ReviewList({ slug, ratingAvg, ratingCount, signedIn }: {
  slug: string; ratingAvg: string; ratingCount: number; signedIn: boolean;
}) {
  const reviews = await getReviews(slug).catch(() => []);
  return (
    <section id="reviews" aria-labelledby="reviews-heading" className="mx-auto mt-16 max-w-3xl scroll-mt-24">
      <div className="flex items-baseline justify-between">
        <h2 id="reviews-heading" className="font-display text-2xl">Customer reviews</h2>
        <ReviewStars rating={ratingAvg} count={ratingCount} />
      </div>
      {reviews.length === 0 ? (
        <p className="mt-6 text-sm text-muted">No reviews yet — be the first to review this product.</p>
      ) : (
        <ul className="mt-6 space-y-6">
          {reviews.map((r) => (
            <li key={`${r.author}-${r.created_at}`} className="rounded-[var(--radius-card)] bg-surface p-5 shadow-sm">
              <div className="flex flex-wrap items-center gap-3">
                <span aria-label={`${r.rating} out of 5 stars`} className="text-gold" role="img">
                  {"★".repeat(r.rating)}{"☆".repeat(5 - r.rating)}
                </span>
                <span className="rounded-full bg-accent/10 px-2.5 py-0.5 text-xs font-medium text-accent">
                  Verified purchase
                </span>
              </div>
              {r.title && <h3 className="mt-2 font-medium">{r.title}</h3>}
              <p className="mt-1.5 text-sm leading-relaxed text-muted">{r.body}</p>
              <p className="mt-3 text-xs text-muted">
                {r.author} · {new Date(r.created_at).toLocaleDateString("en", { year: "numeric", month: "long" })}
              </p>
            </li>
          ))}
        </ul>
      )}
      <ReviewForm slug={slug} signedIn={signedIn} action={submitReviewAction} />
    </section>
  );
}
