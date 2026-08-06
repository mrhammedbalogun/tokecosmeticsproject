"use client";

/**
 * The customer-reviews table with row actions. Reviews publish the moment a customer
 * posts one, so this table is damage control: Hide pulls a review off the product page
 * (reversible), Delete removes it for good behind a TWO-STEP INLINE confirm — no
 * `window.confirm`, which blocks the extension automation (DeliveryOptions ruling).
 *
 * Deletes are optimistic (`removedIds` + router.refresh(), the DeliveryOptions
 * pattern); hide/unhide waits for the server and refreshes, because the row must show
 * the status the backend actually holds.
 */
import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import {
  deleteReviewAction,
  setReviewStatusAction,
} from "@/app/(shell)/reviews/actions";
import type { ReviewRow } from "@/lib/reviews";

const STATUS_STYLE: Record<ReviewRow["status"], string> = {
  approved: "border-ok/30 bg-ok/10 text-ok",
  hidden: "border-warn/30 bg-warn/5 text-warn",
};

const STATUS_LABEL: Record<ReviewRow["status"], string> = {
  approved: "Visible",
  hidden: "Hidden",
};

const ROW_BUTTON = "rounded border border-line px-2 py-1 text-xs hover:border-accent";

export function ReviewsTable({ rows }: { rows: ReviewRow[] }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [message, setMessage] = useState<string | null>(null);
  const [armedId, setArmedId] = useState<number | null>(null);
  const [removedIds, setRemovedIds] = useState<ReadonlySet<number>>(new Set());

  const visible = rows.filter((r) => !removedIds.has(r.id));

  const setStatus = (id: number, status: ReviewRow["status"]) =>
    startTransition(async () => {
      setMessage(null);
      const result = await setReviewStatusAction(id, status);
      if (result.error) setMessage(result.error);
      else router.refresh();
    });

  const remove = (id: number) =>
    startTransition(async () => {
      setMessage(null);
      const result = await deleteReviewAction(id);
      setArmedId(null);
      if (result.error) {
        setMessage(result.error);
        return;
      }
      setRemovedIds((prev) => new Set(prev).add(id));
      router.refresh();
    });

  return (
    <div>
      {message && (
        <p role="alert" className="mb-3 rounded border border-warn/30 bg-warn/5 p-2 text-sm text-warn">
          {message}
        </p>
      )}

      {visible.length === 0 ? (
        <p className="rounded-[var(--radius-card)] border border-line bg-surface p-6 text-center text-sm text-muted">
          No reviews match those filters.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-[var(--radius-card)] border border-line">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-line bg-surface text-left text-xs text-muted">
                <th scope="col" className="p-3 font-medium">Product</th>
                <th scope="col" className="p-3 font-medium">Rating</th>
                <th scope="col" className="p-3 font-medium">Review</th>
                <th scope="col" className="p-3 font-medium">Customer</th>
                <th scope="col" className="p-3 font-medium">Date</th>
                <th scope="col" className="p-3 font-medium">Status</th>
                <th scope="col" className="p-3 font-medium">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {visible.map((row) => (
                <tr key={row.id} className="border-b border-line last:border-0 align-top">
                  <td className="p-3 font-medium">{row.product_name}</td>
                  <td className="p-3">
                    <span aria-label={`${row.rating} out of 5 stars`} className="whitespace-nowrap text-amber-500">
                      {"★".repeat(row.rating)}
                      <span className="text-line">{"★".repeat(5 - row.rating)}</span>
                    </span>
                  </td>
                  <td className="max-w-md p-3">
                    {row.title && <div className="font-medium">{row.title}</div>}
                    <div className="line-clamp-3 text-muted">{row.body}</div>
                  </td>
                  <td className="p-3">
                    <div>{row.author_name}</div>
                    <div className="text-xs text-muted">{row.author_email}</div>
                  </td>
                  <td className="whitespace-nowrap p-3 text-xs text-muted">
                    {/* ISO, not toLocaleDateString: the server's locale is not the reader's. */}
                    {new Date(row.created_at).toISOString().slice(0, 10)}
                  </td>
                  <td className="p-3">
                    <span className={`rounded border px-2 py-0.5 text-xs ${STATUS_STYLE[row.status]}`}>
                      {STATUS_LABEL[row.status]}
                    </span>
                  </td>
                  <td className="whitespace-nowrap p-3">
                    {armedId === row.id ? (
                      <span
                        role="alertdialog"
                        aria-label={`Delete the review of ${row.product_name} by ${row.author_name}?`}
                        className="inline-flex items-center gap-2"
                      >
                        <button
                          type="button"
                          disabled={pending}
                          onClick={() => remove(row.id)}
                          className="rounded bg-warn px-2 py-1 text-xs font-medium text-white hover:opacity-90 disabled:opacity-40"
                        >
                          Delete for good
                        </button>
                        <button
                          type="button"
                          disabled={pending}
                          onClick={() => setArmedId(null)}
                          className={ROW_BUTTON}
                        >
                          Keep it
                        </button>
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-2">
                        {row.status === "approved" ? (
                          <button
                            type="button"
                            disabled={pending}
                            onClick={() => setStatus(row.id, "hidden")}
                            className={ROW_BUTTON}
                          >
                            Hide
                          </button>
                        ) : (
                          <button
                            type="button"
                            disabled={pending}
                            onClick={() => setStatus(row.id, "approved")}
                            className={ROW_BUTTON}
                          >
                            Unhide
                          </button>
                        )}
                        <button
                          type="button"
                          disabled={pending}
                          onClick={() => setArmedId(row.id)}
                          className={`${ROW_BUTTON} hover:border-warn hover:text-warn`}
                        >
                          Delete
                        </button>
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
