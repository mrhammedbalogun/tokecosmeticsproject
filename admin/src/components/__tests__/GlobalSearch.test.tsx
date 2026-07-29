import { describe, it, expect, vi, afterEach } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { GlobalSearch, SearchPanelBody } from "@/components/GlobalSearch";
import { SEARCH_DEBOUNCE_MS } from "@/lib/search";
import type { SearchState } from "@/lib/search";

afterEach(() => {
  vi.restoreAllMocks();
});

const ORDER = {
  number: "TC-100123",
  legacy_number: "",
  status: "pending_payment",
  grand_total: "18500.00",
  currency: "NGN",
  email: "buyer@example.test",
  placed_at: "2026-07-01T10:00:00Z",
};

const CUSTOMER = {
  toke_id: "TK-7X4KQZ",
  email: "buyer@example.test",
  name: "Ada Buyer",
  is_active: true,
  date_joined: "2026-01-01T00:00:00Z",
};

const PRODUCT = { name: "Zeta Cream", slug: "zeta-cream", status: "active", skus: ["ZETA-50"] };

function panel(state: SearchState | null, isPending = false) {
  return render(<SearchPanelBody state={state} isPending={isPending} />);
}

describe("the results panel", () => {
  it("answers the two phone questions inline, with no links to nowhere", () => {
    // THE POINT OF THE WHOLE FRONTEND DESIGN. Plans 17/18 have not built the detail pages,
    // so a linked result would be a 404. The status, the total and the customer are on the
    // card instead — which is what somebody on the phone actually needs.
    const { container } = panel({
      query: "TC-100123",
      results: { orders: [ORDER], customers: [CUSTOMER] },
    });

    expect(screen.getByText("TC-100123")).toBeInTheDocument();
    expect(screen.getByText(/Pending payment · NGN 18500.00 · buyer@example.test/)).toBeInTheDocument();
    expect(screen.getByText("Ada Buyer")).toBeInTheDocument();
    expect(screen.getByText("TK-7X4KQZ")).toBeInTheDocument();
    expect(container.querySelectorAll("a")).toHaveLength(0);
  });

  it("renders only the sections the response carried", () => {
    // Support's shape: `products` is absent because that section is behind
    // `products.manage`. The component renders what it is given and filters nothing —
    // re-deciding scope in the browser would be a second, weaker copy of the rule.
    panel({ query: "zeta", results: { orders: [ORDER], customers: [CUSTOMER] } });

    expect(screen.getByText("Orders")).toBeInTheDocument();
    expect(screen.getByText("Customers")).toBeInTheDocument();
    expect(screen.queryByText("Products")).not.toBeInTheDocument();
  });

  it("shows the same 'no matches' message when the caller's role granted no sections", () => {
    // A Content editor gets `{}`. Saying "you may not search orders" would teach a stolen
    // session which surfaces exist and are worth attacking; the backend answers an empty
    // 200 for the same reason.
    panel({ query: "buyer@example.test", results: {} });

    expect(screen.getByText(/No matches for/)).toBeInTheDocument();
    expect(screen.queryByText("Orders")).not.toBeInTheDocument();
  });

  it("says the cap is a cap, so nobody reads ten results as all of them", () => {
    panel({ query: "zeta", results: { products: [PRODUCT] } });

    expect(screen.getByText(/up to 10 per section/i)).toBeInTheDocument();
  });

  it("flags a customer inside the deletion grace window", () => {
    panel({
      query: "ada",
      results: { customers: [{ ...CUSTOMER, is_active: false }] },
    });

    expect(screen.getByText(/deletion requested/i)).toBeInTheDocument();
  });

  it("shows a legacy order number when the order has one", () => {
    panel({ query: "NG-5150", results: { orders: [{ ...ORDER, legacy_number: "NG-5150" }] } });

    expect(screen.getByText(/was NG-5150/)).toBeInTheDocument();
  });

  it("reports an error instead of pretending there were no results", () => {
    panel({ query: "zeta", results: null, error: "Too many searches. Try again in a minute." });

    expect(screen.getByRole("alert")).toHaveTextContent(/too many searches/i);
  });
});

/** Type into the box and let the debounce fire. `fireEvent` rather than `user-event`,
 *  which this app does not depend on (see `TotpPanel.test.tsx` for the same choice). */
async function typeAndSettle(value: string) {
  const box = screen.getByRole("combobox");
  fireEvent.change(box, { target: { value } });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(SEARCH_DEBOUNCE_MS + 50);
  });
  return box;
}

describe("the search box", () => {
  it("does not call the action below the minimum length, and debounces once above it", async () => {
    vi.useFakeTimers();
    try {
      const action = vi.fn(async (term: string) => ({ query: term, results: {} }));
      render(<GlobalSearch action={action} />);

      await typeAndSettle("ze");
      expect(action).not.toHaveBeenCalled();

      // Three keystrokes in quick succession must produce ONE call, not three: the
      // per-user throttle is 60/min and a request per keystroke would spend it typing an
      // email address.
      const box = screen.getByRole("combobox");
      fireEvent.change(box, { target: { value: "zet" } });
      fireEvent.change(box, { target: { value: "zeta" } });
      fireEvent.change(box, { target: { value: "zeta1" } });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(SEARCH_DEBOUNCE_MS + 50);
      });

      expect(action).toHaveBeenCalledTimes(1);
      expect(action).toHaveBeenCalledWith("zeta1");
    } finally {
      vi.useRealTimers();
    }
  });

  it("discards a response that no longer matches what the box says", async () => {
    // Two searches in flight can land out of order. Showing results for "zet" under a box
    // reading "zeta" is the kind of small wrongness that makes somebody distrust the panel.
    vi.useFakeTimers();
    try {
      const action = vi.fn(async () => ({
        query: "zet", // a reply for a term the box has already moved past
        results: { products: [PRODUCT] },
      }));
      render(<GlobalSearch action={action} />);

      await typeAndSettle("zeta");

      expect(action).toHaveBeenCalledWith("zeta");
      expect(screen.queryByText("Zeta Cream")).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("renders the results once the reply matches the term", async () => {
    vi.useFakeTimers();
    try {
      const action = vi.fn(async (term: string) => ({
        query: term,
        results: { products: [PRODUCT] },
      }));
      render(<GlobalSearch action={action} />);

      await typeAndSettle("zeta");
      // A second flush: the state lands inside `startTransition`, one microtask after the
      // debounce timer fires. `waitFor` cannot be used here — it polls on a real clock
      // that fake timers have stopped.
      await act(async () => {});

      expect(screen.getByText("Zeta Cream")).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });
});
