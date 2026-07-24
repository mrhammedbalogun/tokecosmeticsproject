/** Gold stars (design token --color-gold). rating is the API string ("4.50").
 * Renders nothing when there are no reviews so cards stay uncluttered. */
export function ReviewStars({
  rating,
  count,
  showCount = true,
}: {
  rating: string;
  count: number;
  showCount?: boolean;
}) {
  const value = Number(rating);
  if (count === 0) return null;
  return (
    <span
      className="inline-flex items-center gap-1 text-sm"
      aria-label={`Rated ${rating} out of 5 from ${count} reviews`}
    >
      <span aria-hidden className="tracking-tight text-gold">
        {[1, 2, 3, 4, 5].map((i) => (i <= Math.round(value) ? "★" : "☆")).join("")}
      </span>
      {showCount && <span className="text-muted">({count})</span>}
    </span>
  );
}
