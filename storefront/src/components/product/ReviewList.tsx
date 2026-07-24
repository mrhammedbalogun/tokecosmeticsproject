import { getReviews } from "@/lib/catalog";
import { ReviewStars } from "@/components/product/ReviewStars";

/** Approved reviews. Every one is a verified purchase by backend construction
 * (only verified purchasers can post), so the badge is unconditional. */
export async function ReviewList({ slug, ratingAvg, ratingCount }: {
  slug: string; ratingAvg: string; ratingCount: number;
}) {
  const reviews = await getReviews(slug).catch(() => []);
  if (reviews.length === 0) return null;
  return (
    <section aria-labelledby="reviews-heading" className="mx-auto mt-16 max-w-3xl">
      <div className="flex items-baseline justify-between">
        <h2 id="reviews-heading" className="font-display text-2xl">Customer reviews</h2>
        <ReviewStars rating={ratingAvg} count={ratingCount} />
      </div>
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
    </section>
  );
}
