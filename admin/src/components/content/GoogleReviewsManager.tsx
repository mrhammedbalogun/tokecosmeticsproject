"use client";

/** Curation surface for the homepage's Google reviews (landing redesign).
 *
 * Curated on purpose — but NOT for the reason first written here. The Places API
 * does return a per-review permalink now; what it does not allow is KEEPING the
 * review. Maps Platform Service Specific Terms §14.3 permits caching latitude and
 * longitude from the Places API and nothing else, so an API-pulled review cannot
 * live in our database. A human transcribes it instead. Full reasoning on the
 * `cms.GoogleReview` model; sanctioned automation route (Google Business Profile
 * API) in `docs/runbooks/google-apis-setup.md`.
 *
 * The header rating/count are NO LONGER hand-entered — a nightly Place Details
 * call overwrites them, which is why those two fields are shown as synced.
 */
import { startTransition, useState } from "react";
import {
  deleteReviewAction,
  saveReviewAction,
  saveReviewsMetaAction,
  type ReviewState,
} from "@/app/(shell)/content/reviews/actions";

export interface ReviewRow {
  id: number;
  author: string;
  location: string;
  rating: number;
  text: string;
  review_url: string;
  reviewed_at_text: string;
  sort: number;
  is_active: boolean;
}

export interface ReviewsMeta {
  rating: string | null;
  review_count_text: string;
  profile_url: string;
}

const FIELD =
  "w-full rounded border border-line bg-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none";

export function GoogleReviewsManager({
  reviews,
  meta,
}: {
  reviews: ReviewRow[];
  meta: ReviewsMeta;
}) {
  const [editing, setEditing] = useState<ReviewRow | null>(null);
  const [creating, setCreating] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  return (
    <div className="space-y-6">
      <MetaForm meta={meta} />

      {message && (
        <p className="rounded border border-warn/30 bg-warn/5 p-2 text-sm text-warn" role="alert">
          {message}
        </p>
      )}

      {!creating && !editing && (
        <button
          type="button"
          onClick={() => setCreating(true)}
          className="rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90"
        >
          Feature a review
        </button>
      )}

      {(creating || editing) && (
        <ReviewForm
          review={editing}
          onDone={() => {
            setCreating(false);
            setEditing(null);
          }}
        />
      )}

      {reviews.length === 0 ? (
        <p className="rounded-[var(--radius-card)] border border-dashed border-line p-6 text-center text-sm text-muted">
          No featured reviews yet — the shop simply hides the section until there is one.
        </p>
      ) : (
        <ul className="divide-y divide-line rounded-[var(--radius-card)] border border-line">
          {reviews.map((review) => (
            <li key={review.id} className="flex items-start justify-between gap-4 p-3 text-sm">
              <div className="min-w-0">
                <p>
                  <span className="font-medium">{review.author}</span>
                  <span className="ml-2 text-gold">{"★".repeat(review.rating)}</span>
                  {!review.is_active && <span className="ml-2 text-xs text-muted">(hidden)</span>}
                </p>
                <p className="mt-0.5 truncate text-muted">{review.text}</p>
              </div>
              <span className="flex shrink-0 gap-2">
                <button
                  type="button"
                  onClick={() => setEditing(review)}
                  className="rounded border border-line px-2 py-1 text-xs hover:border-accent"
                >
                  Edit
                </button>
                <button
                  type="button"
                  onClick={() =>
                    startTransition(async () => {
                      const state = await deleteReviewAction(review.id);
                      setMessage(state.message ?? null);
                    })
                  }
                  className="rounded border border-line px-2 py-1 text-xs hover:border-warn hover:text-warn"
                >
                  Remove
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function MetaForm({ meta }: { meta: ReviewsMeta }) {
  const [state, setState] = useState<ReviewState>({});
  const [pending, setPending] = useState(false);
  return (
    <form
      className="rounded-[var(--radius-card)] border border-line p-4"
      onSubmit={(e) => {
        e.preventDefault();
        const data = new FormData(e.currentTarget);
        setPending(true);
        startTransition(async () => {
          setState(
            await saveReviewsMetaAction({
              rating: String(data.get("rating") ?? ""),
              review_count_text: String(data.get("review_count_text") ?? ""),
              profile_url: String(data.get("profile_url") ?? ""),
            }),
          );
          setPending(false);
        });
      }}
    >
      <h2 className="text-sm font-medium">Header numbers</h2>
      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <label className="text-xs">
          Overall rating (e.g. 4.8)
          <input name="rating" defaultValue={meta.rating ?? ""} className={FIELD} />
        </label>
        <label className="text-xs">
          Review count text (e.g. 300+)
          <input name="review_count_text" defaultValue={meta.review_count_text} className={FIELD} />
        </label>
        <label className="text-xs">
          Google profile URL (Review us button)
          <input name="profile_url" defaultValue={meta.profile_url} className={FIELD} />
        </label>
      </div>
      <div className="mt-3 flex items-center gap-3">
        <button
          type="submit"
          disabled={pending}
          className="rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-40"
        >
          {pending ? "Saving…" : "Save numbers"}
        </button>
        {state.message && <span className="text-xs text-muted">{state.message}</span>}
      </div>
    </form>
  );
}

function ReviewForm({ review, onDone }: { review: ReviewRow | null; onDone: () => void }) {
  const [state, setState] = useState<ReviewState>({});
  const [pending, setPending] = useState(false);
  const err = (key: string) => state.fieldErrors?.[key];
  return (
    <form
      className="rounded-[var(--radius-card)] border border-line p-4"
      onSubmit={(e) => {
        e.preventDefault();
        const data = new FormData(e.currentTarget);
        setPending(true);
        startTransition(async () => {
          const result = await saveReviewAction({
            id: review?.id,
            author: String(data.get("author") ?? ""),
            location: String(data.get("location") ?? ""),
            rating: Number(data.get("rating") ?? 5),
            text: String(data.get("text") ?? ""),
            review_url: String(data.get("review_url") ?? ""),
            reviewed_at_text: String(data.get("reviewed_at_text") ?? ""),
            is_active: data.get("is_active") === "on",
          });
          setPending(false);
          setState(result);
          if (!result.fieldErrors && !result.message?.includes("could not")) onDone();
        });
      }}
    >
      <h2 className="text-sm font-medium">{review ? "Edit review" : "Feature a review"}</h2>
      <p className="mt-1 text-xs text-muted">
        On Google Maps: find the review → ⋮ → Share review → Copy link. That link is what
        makes the card open the exact review. Type the review text out as it appears on
        Google — quote it, don&apos;t paraphrase. The homepage grid fits 4 or 5 across;
        6 or 7 will leave a short final row.
      </p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <label className="text-xs">
          Author (as shown on Google)
          <input name="author" defaultValue={review?.author} className={FIELD} />
          {err("author") && <span className="text-warn">{err("author")}</span>}
        </label>
        <label className="text-xs">
          Location (optional, e.g. Lagos)
          <input name="location" defaultValue={review?.location} className={FIELD} />
        </label>
        <label className="text-xs">
          Stars
          <select name="rating" defaultValue={review?.rating ?? 5} className={FIELD}>
            {[5, 4, 3, 2, 1].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs">
          When (verbatim, e.g. “2 weeks ago”)
          <input name="reviewed_at_text" defaultValue={review?.reviewed_at_text} className={FIELD} />
        </label>
        <label className="text-xs sm:col-span-2">
          Review text
          <textarea name="text" rows={3} defaultValue={review?.text} className={FIELD} />
          {err("text") && <span className="text-warn">{err("text")}</span>}
        </label>
        <label className="text-xs sm:col-span-2">
          Google share-link
          <input name="review_url" defaultValue={review?.review_url} className={FIELD} />
          {err("review_url") && <span className="text-warn">{err("review_url")}</span>}
        </label>
        <label className="flex items-center gap-2 text-xs">
          <input type="checkbox" name="is_active" defaultChecked={review?.is_active ?? true} />
          Shown on the homepage
        </label>
      </div>
      {state.message && <p className="mt-2 text-xs text-warn">{state.message}</p>}
      <div className="mt-3 flex gap-2">
        <button
          type="submit"
          disabled={pending}
          className="rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-40"
        >
          {pending ? "Saving…" : "Save review"}
        </button>
        <button
          type="button"
          onClick={onDone}
          className="rounded border border-line px-3 py-1.5 text-sm hover:border-accent"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
