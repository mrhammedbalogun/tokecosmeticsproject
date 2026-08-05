"use client";

/**
 * The write half of the PDP reviews section. Which state it renders is decided by
 * the eligibility probe (BFF: /api/products/[slug]/reviews/eligibility):
 *
 *   signed out      → "sign in to review" link (no probe — the server already knows)
 *   not a purchaser → one muted line; reviews here are verified purchases only
 *   already reviewed→ note, plus "awaiting approval" while it is pending
 *   eligible        → the form (star radio group + title + body, Server Function submit)
 *
 * A probe failure renders nothing: a broken nicety must not clutter a public PDP.
 * Follows LoginForm's conventions: live region present from first paint, native
 * validation on, submit disabled only while pending.
 */
import { useActionState, useEffect, useState } from "react";
import { LOGIN_PATH, withNext } from "@/lib/auth-guard";
import type { ReviewFormState } from "@/app/(shop)/product/[slug]/actions";

const ERROR_ID = "review-error";

const inputClass =
  "w-full rounded-[var(--radius-card)] border border-line bg-beige px-3 py-2 text-sm " +
  "focus:outline-none focus:ring-2 focus:ring-accent/40";

interface Eligibility {
  eligible: boolean;
  has_reviewed: boolean;
  review_status: "pending" | "approved" | "rejected" | null;
}

type Phase =
  | { kind: "loading" }
  | { kind: "signed-out" }
  | { kind: "not-purchaser" }
  | { kind: "reviewed"; status: Eligibility["review_status"] }
  | { kind: "eligible" }
  | { kind: "hidden" };

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="mt-8 rounded-[var(--radius-card)] bg-surface p-5 shadow-sm">
      {children}
    </div>
  );
}

export function ReviewForm({
  slug,
  signedIn,
  action,
}: {
  slug: string;
  signedIn: boolean;
  action: (state: ReviewFormState, formData: FormData) => Promise<ReviewFormState>;
}) {
  const [phase, setPhase] = useState<Phase>(
    signedIn ? { kind: "loading" } : { kind: "signed-out" },
  );
  const [state, formAction, pending] = useActionState(action, {} as ReviewFormState);
  const [rating, setRating] = useState(0);
  const [hovered, setHovered] = useState(0);

  useEffect(() => {
    if (!signedIn) return;
    let cancelled = false;
    fetch(`/api/products/${encodeURIComponent(slug)}/reviews/eligibility`)
      .then(async (res) => {
        if (cancelled) return;
        if (res.status === 401) return setPhase({ kind: "signed-out" });
        if (!res.ok) return setPhase({ kind: "hidden" });
        const data = (await res.json()) as Eligibility;
        if (cancelled) return;
        if (data.eligible) setPhase({ kind: "eligible" });
        else if (data.has_reviewed) setPhase({ kind: "reviewed", status: data.review_status });
        else setPhase({ kind: "not-purchaser" });
      })
      .catch(() => { if (!cancelled) setPhase({ kind: "hidden" }); });
    return () => { cancelled = true; };
  }, [slug, signedIn]);

  if (phase.kind === "loading" || phase.kind === "hidden") return null;

  if (phase.kind === "signed-out") {
    return (
      <Shell>
        <p className="text-sm text-muted">
          Bought this product?{" "}
          <a
            href={withNext(LOGIN_PATH, `/product/${slug}`)}
            className="font-medium text-accent underline-offset-2 hover:underline"
          >
            Sign in
          </a>{" "}
          to write a review.
        </p>
      </Shell>
    );
  }

  if (phase.kind === "not-purchaser") {
    return (
      <p className="mt-8 text-sm text-muted">
        Reviews are written by customers who purchased this product.
      </p>
    );
  }

  if (phase.kind === "reviewed") {
    return (
      <Shell>
        <p role="status" className="text-sm text-muted">
          You&apos;ve already reviewed this product.
          {phase.status === "pending" && " Your review is awaiting approval."}
        </p>
      </Shell>
    );
  }

  if (state.submitted) {
    return (
      <Shell>
        <p role="status" className="text-sm text-accent-strong">
          Thank you! Your review has been submitted and will appear once it&apos;s approved.
        </p>
      </Shell>
    );
  }

  const lit = hovered || rating;

  return (
    <Shell>
      <h3 className="font-medium">Write a review</h3>
      <form action={formAction} className="mt-4 space-y-4">
        <div aria-live="polite">
          {state.error && (
            <p id={ERROR_ID} role="alert" className="text-sm text-red-700">
              {state.error}
            </p>
          )}
        </div>

        <input type="hidden" name="slug" value={slug} />

        <fieldset onMouseLeave={() => setHovered(0)}>
          <legend className="mb-1 block text-sm font-medium">Your rating</legend>
          <div className="flex gap-0.5">
            {[1, 2, 3, 4, 5].map((n) => (
              <label
                key={n}
                className="cursor-pointer"
                onMouseEnter={() => setHovered(n)}
              >
                <input
                  type="radio"
                  name="rating"
                  value={n}
                  required
                  checked={rating === n}
                  onChange={() => setRating(n)}
                  className="peer sr-only"
                />
                <span
                  aria-hidden
                  className={`rounded text-2xl transition-colors peer-focus-visible:ring-2 peer-focus-visible:ring-accent/40 ${
                    n <= lit ? "text-gold" : "text-line"
                  }`}
                >
                  ★
                </span>
                <span className="sr-only">{n === 1 ? "1 star" : `${n} stars`}</span>
              </label>
            ))}
          </div>
        </fieldset>

        <div>
          <label htmlFor="review-title" className="mb-1 block text-sm font-medium">
            Title <span className="font-normal text-muted">(optional)</span>
          </label>
          <input
            id="review-title"
            name="title"
            type="text"
            maxLength={140}
            className={inputClass}
          />
        </div>

        <div>
          <label htmlFor="review-body" className="mb-1 block text-sm font-medium">
            Your review
          </label>
          <textarea
            id="review-body"
            name="body"
            required
            maxLength={4000}
            rows={4}
            aria-invalid={state.error ? true : undefined}
            aria-describedby={state.error ? ERROR_ID : undefined}
            className={inputClass}
          />
        </div>

        <button
          type="submit"
          disabled={pending}
          className="rounded-[var(--radius-card)] bg-accent px-4 py-2 text-sm text-surface transition-colors hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-60"
        >
          {pending ? "Submitting…" : "Submit review"}
        </button>
      </form>
    </Shell>
  );
}
