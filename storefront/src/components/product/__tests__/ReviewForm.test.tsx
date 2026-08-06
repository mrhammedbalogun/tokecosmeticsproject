import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ReviewForm } from "@/components/product/ReviewForm";
import type { ReviewFormState } from "@/app/(shop)/product/[slug]/actions";

const refreshSpy = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: refreshSpy }) }));

const ELIGIBILITY_URL = "/api/products/shea-butter/reviews/eligibility";

function mockEligibility(status: number, body: unknown) {
  const f = vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url !== ELIGIBILITY_URL) {
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    }
    return Promise.resolve(
      new Response(JSON.stringify(body), {
        status, headers: { "content-type": "application/json" },
      }),
    );
  });
  global.fetch = f as unknown as typeof fetch;
  return f;
}

const noopAction = async (): Promise<ReviewFormState> => ({});

const originalFetch = global.fetch;
afterEach(() => { global.fetch = originalFetch; vi.restoreAllMocks(); });

describe("ReviewForm", () => {
  it("shows a sign-in link (and never probes) when signed out", () => {
    const f = vi.fn();
    global.fetch = f as unknown as typeof fetch;

    render(<ReviewForm slug="shea-butter" signedIn={false} action={noopAction} />);

    const link = screen.getByRole("link", { name: "Sign in" });
    expect(link).toHaveAttribute("href", "/login?next=%2Fproduct%2Fshea-butter");
    expect(f).not.toHaveBeenCalled();
  });

  it("shows the form to an eligible purchaser", async () => {
    mockEligibility(200, { eligible: true, has_reviewed: false, review_status: null });

    render(<ReviewForm slug="shea-butter" signedIn action={noopAction} />);

    expect(await screen.findByRole("button", { name: "Submit review" })).toBeInTheDocument();
    expect(screen.getByLabelText("Your review")).toBeRequired();
    expect(screen.getAllByRole("radio")).toHaveLength(5);
  });

  it("shows a note instead of the form to a non-purchaser", async () => {
    mockEligibility(200, { eligible: false, has_reviewed: false, review_status: null });

    render(<ReviewForm slug="shea-butter" signedIn action={noopAction} />);

    expect(
      await screen.findByText(/reviews are written by customers who purchased/i),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Submit review" })).not.toBeInTheDocument();
  });

  it("tells a customer who already reviewed (hidden included) — no form", async () => {
    mockEligibility(200, { eligible: false, has_reviewed: true, review_status: "hidden" });

    render(<ReviewForm slug="shea-butter" signedIn action={noopAction} />);

    expect(await screen.findByRole("status")).toHaveTextContent(/already reviewed/i);
    expect(screen.queryByRole("button", { name: "Submit review" })).not.toBeInTheDocument();
  });

  it("falls back to the sign-in link when the probe answers 401", async () => {
    mockEligibility(401, { detail: "Not authenticated." });

    render(<ReviewForm slug="shea-butter" signedIn action={noopAction} />);

    expect(await screen.findByRole("link", { name: "Sign in" })).toBeInTheDocument();
  });

  it("replaces the form with a live notice and refreshes the list on success", async () => {
    mockEligibility(200, { eligible: true, has_reviewed: false, review_status: null });
    const action = vi.fn(
      async (_s: ReviewFormState, _fd: FormData): Promise<ReviewFormState> => ({ submitted: true }),
    );

    render(<ReviewForm slug="shea-butter" signedIn action={action} />);

    fireEvent.click(await screen.findByRole("radio", { name: "5 stars" }));
    fireEvent.change(screen.getByLabelText("Your review"), {
      target: { value: "Lovely texture." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Submit review" }));

    expect(await screen.findByRole("status")).toHaveTextContent(/review is now live/i);
    expect(action).toHaveBeenCalledTimes(1);
    const fd = action.mock.calls[0]![1];
    expect(fd.get("rating")).toBe("5");
    expect(fd.get("body")).toBe("Lovely texture.");
    expect(fd.get("slug")).toBe("shea-butter");
    await waitFor(() => expect(refreshSpy).toHaveBeenCalled());
  });

  it("announces the action error in the live region", async () => {
    mockEligibility(200, { eligible: true, has_reviewed: false, review_status: null });
    const action = vi.fn(async (): Promise<ReviewFormState> => ({
      error: "You have already reviewed this product.",
    }));

    render(<ReviewForm slug="shea-butter" signedIn action={action} />);

    fireEvent.click(await screen.findByRole("radio", { name: "1 star" }));
    fireEvent.change(screen.getByLabelText("Your review"), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit review" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/already reviewed/i);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Submit review" })).toBeEnabled(),
    );
  });
});
