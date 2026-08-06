import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import type { ReviewRow } from "@/lib/reviews";

const setStatus = vi.fn<(id: number, status: string) => Promise<{ error?: string }>>(
  async () => ({}),
);
const del = vi.fn<(id: number) => Promise<{ error?: string }>>(async () => ({}));
vi.mock("@/app/(shell)/reviews/actions", () => ({
  setReviewStatusAction: (id: number, status: string) => setStatus(id, status),
  deleteReviewAction: (id: number) => del(id),
}));

const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));

import { ReviewsTable } from "@/components/reviews/ReviewsTable";

function row(overrides: Partial<ReviewRow> = {}): ReviewRow {
  return {
    id: 1,
    product_name: "Shea Butter Cream",
    product_slug: "shea-butter-cream",
    author_name: "Ada",
    author_email: "ada@x.com",
    rating: 4,
    title: "Lovely",
    body: "Really lovely texture.",
    status: "approved",
    created_at: "2026-08-01T10:00:00Z",
    ...overrides,
  };
}

beforeEach(() => {
  setStatus.mockClear();
  del.mockClear();
  refresh.mockClear();
});

describe("ReviewsTable", () => {
  it("hides a visible review and refreshes", async () => {
    render(<ReviewsTable rows={[row()]} />);

    fireEvent.click(screen.getByRole("button", { name: "Hide" }));

    await waitFor(() => expect(setStatus).toHaveBeenCalledWith(1, "hidden"));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
  });

  it("offers Unhide for a hidden review", async () => {
    render(<ReviewsTable rows={[row({ status: "hidden" })]} />);

    expect(screen.getByText("Hidden")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Unhide" }));

    await waitFor(() => expect(setStatus).toHaveBeenCalledWith(1, "approved"));
  });

  it("does NOT delete until the inline confirm is accepted", async () => {
    render(<ReviewsTable rows={[row()]} />);

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(del).not.toHaveBeenCalled();

    // Backing out disarms and deletes nothing.
    fireEvent.click(screen.getByRole("button", { name: "Keep it" }));
    expect(del).not.toHaveBeenCalled();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete for good" }));

    await waitFor(() => expect(del).toHaveBeenCalledWith(1));
    // Optimistic removal: the row is gone without waiting for the server round-trip.
    await waitFor(() =>
      expect(screen.queryByText("Shea Butter Cream")).not.toBeInTheDocument(),
    );
  });

  it("surfaces an action error in the alert region and keeps the row", async () => {
    setStatus.mockResolvedValueOnce({ error: "Your role does not include managing reviews." });
    render(<ReviewsTable rows={[row()]} />);

    fireEvent.click(screen.getByRole("button", { name: "Hide" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/does not include/i);
    expect(screen.getByText("Shea Butter Cream")).toBeInTheDocument();
    expect(refresh).not.toHaveBeenCalled();
  });
});
