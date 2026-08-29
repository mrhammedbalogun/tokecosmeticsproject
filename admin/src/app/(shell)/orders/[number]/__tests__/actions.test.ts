import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const store = new Map<string, string>();
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (n: string) => (store.has(n) ? { name: n, value: store.get(n) } : undefined),
    set: (n: string, v: string) => store.set(n, v),
    delete: (n: string) => store.delete(n),
  }),
}));

const revalidatePath = vi.fn();
vi.mock("next/cache", () => ({ revalidatePath: (p: string) => revalidatePath(p) }));

import {
  aajCaptureAction,
  confirmReceiptAction,
  gigCaptureAction,
  manualRefundAction,
  resolveReviewAction,
  trackingAction,
  transitionAction,
} from "../actions";

const originalFetch = global.fetch;
beforeEach(() => {
  process.env.API_URL = "http://backend:8000";
  store.clear();
  store.set("admin_access", "ACCESS");
  revalidatePath.mockClear();
});
afterEach(() => {
  global.fetch = originalFetch;
  vi.restoreAllMocks();
});

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function mockFetch(response: Response) {
  const fn = vi.fn(async () => response);
  global.fetch = fn as unknown as typeof fetch;
  return fn;
}

const sent = (fn: ReturnType<typeof vi.fn>) =>
  JSON.parse((fn.mock.calls[0][1] as RequestInit).body as string);

const confirmInput = (over = {}) => ({
  number: "TC-100001",
  amountReceived: "2000.00",
  bankReference: "REF1",
  note: "",
  acceptDiscrepancy: false,
  allowDuplicateReference: false,
  ...over,
});

describe("confirmReceiptAction", () => {
  it("NORMALISES THE BANK REFERENCE, because the backend guard is an exact match", async () => {
    // payments/services.py:318 compares the reference exactly, so "ref 123", "REF  123"
    // and " REF123 " are three different references to it — and a single space would
    // defeat the cheapest control the system has against shipping goods twice against one
    // transfer. Normalised HERE rather than in the component so it runs whatever calls
    // this: a Server Function is a public endpoint.
    const fetchMock = mockFetch(json({ status: "processing", review_reason: "" }));

    await confirmReceiptAction(confirmInput({ bankReference: "  ref   123  " }));

    expect(sent(fetchMock).bank_reference).toBe("REF 123");
  });

  it("refuses an empty reference without calling the API", async () => {
    const fetchMock = mockFetch(json({}));

    const state = await confirmReceiptAction(confirmInput({ bankReference: "   " }));

    expect(state.error).toMatch(/stops one transfer paying twice/i);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("refuses an amount that is not money", async () => {
    const fetchMock = mockFetch(json({}));

    for (const amountReceived of ["", "abc", "-5", "0", "1,000", "1.234"]) {
      expect((await confirmReceiptAction(confirmInput({ amountReceived }))).error).toBeTruthy();
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("RETURNS BOTH NUMBERS on a discrepancy so the panel can show the delta", async () => {
    mockFetch(
      json(
        {
          detail: "Amount does not match.",
          code: "amount_discrepancy",
          expected: "2000.00",
          received: "2500.00",
        },
        400,
      ),
    );

    const state = await confirmReceiptAction(confirmInput());

    expect(state.code).toBe("amount_discrepancy");
    expect(state.expected).toBe("2000.00");
    expect(state.received).toBe("2500.00");
    expect(state.error).toBe("Amount does not match.");
  });

  it("surfaces a duplicate reference as its own case", async () => {
    mockFetch(json({ detail: "Already used.", code: "duplicate_bank_reference" }, 409));

    const state = await confirmReceiptAction(confirmInput());

    expect(state.code).toBe("duplicate_bank_reference");
  });

  it("forwards the overrides only when asked", async () => {
    const fetchMock = mockFetch(json({ status: "processing", review_reason: "" }));

    await confirmReceiptAction(confirmInput({ acceptDiscrepancy: true }));

    expect(sent(fetchMock).accept_discrepancy).toBe(true);
    expect(sent(fetchMock).allow_duplicate_reference).toBe(false);
  });

  it("revalidates the order and the queue on success", async () => {
    mockFetch(json({ status: "processing", review_reason: "" }));

    await confirmReceiptAction(confirmInput());

    expect(revalidatePath).toHaveBeenCalledWith("/orders/TC-100001");
    expect(revalidatePath).toHaveBeenCalledWith("/orders");
  });

  it("does not revalidate when the confirm failed", async () => {
    mockFetch(json({ detail: "no", code: "invalid_confirmation" }, 400));

    await confirmReceiptAction(confirmInput());

    expect(revalidatePath).not.toHaveBeenCalled();
  });
});

describe("manualRefundAction", () => {
  it("normalises its reference too", async () => {
    const fetchMock = mockFetch(json({}, 201));

    await manualRefundAction({
      number: "TC-100001", amount: "500.00", bankReference: " ref 9 ", note: "", restock: true,
    });

    expect(sent(fetchMock).bank_reference).toBe("REF 9");
  });

  it("SAYS IT RECORDED rather than sent, because it moved no money", async () => {
    // Collapsing the two refund paths into one verb is how somebody comes to believe money
    // moved when they still have to go and wire it.
    mockFetch(json({}, 201));

    const state = await manualRefundAction({
      number: "TC-100001", amount: "500.00", bankReference: "REF9", note: "", restock: true,
    });

    expect(state.success).toMatch(/you sent it/i);
  });
});

describe("transitionAction", () => {
  it("sends the status and the timeline message", async () => {
    const fetchMock = mockFetch(json({}));

    await transitionAction({ number: "TC-100001", toStatus: "shipped", message: "packed" });

    expect(sent(fetchMock)).toEqual({ to_status: "shipped", message: "packed" });
  });

  it("surfaces the backend's refusal verbatim", async () => {
    // The endpoint refuses `refunded` with a sentence explaining why (backend-v0.5.2).
    // Replacing it with "something went wrong" removes the only useful part.
    mockFetch(
      json({ error: "refund_required", detail: "This order still holds captured payment…" }, 400),
    );

    const state = await transitionAction({
      number: "TC-100001", toStatus: "refunded", message: "",
    });

    expect(state.error).toMatch(/still holds captured payment/);
  });

  it("explains a 403 as a role problem", async () => {
    mockFetch(json({ detail: "nope" }, 403));

    const state = await transitionAction({
      number: "TC-100001", toStatus: "cancelled", message: "",
    });

    expect(state.error).toMatch(/role does not allow/i);
  });

  it("refuses an order number that could not be interpolated safely", async () => {
    const fetchMock = mockFetch(json({}));

    const state = await transitionAction({
      number: "../../etc", toStatus: "shipped", message: "",
    });

    expect(state.error).toMatch(/could not be identified/i);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("trackingAction", () => {
  it("says the customer is not emailed yet", async () => {
    // Recording tracking sends nothing; moving to shipped is what mails them.
    mockFetch(json({}));

    const state = await trackingAction({
      number: "TC-100001", carrier: "GIG", trackingNumber: "123",
    });

    expect(state.success).toMatch(/when you mark it shipped/i);
  });

  it("needs both halves", async () => {
    const fetchMock = mockFetch(json({}));

    const state = await trackingAction({ number: "TC-100001", carrier: "GIG", trackingNumber: " " });

    expect(state.error).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("resolveReviewAction", () => {
  it("says clearing the flag moved no money", async () => {
    mockFetch(json({}));

    const state = await resolveReviewAction({ number: "TC-100001" });

    expect(state.success).toMatch(/no money moved/i);
  });
});


describe("gigCaptureAction", () => {
  it("forwards GIG's own refusal with its code, and revalidates — the failure is history now", async () => {
    // The backend records a refused capture on the order timeline (delivery/gig/capture.py),
    // so the page under this panel is stale the moment the action returns. Before that
    // record existed, a failed capture left no trace anywhere a person could read.
    mockFetch(json(
      { error: "gig_rejected", detail: "Insufficient wallet balance.", api_id: "trace-77" },
      502,
    ));
    const state = await gigCaptureAction({ number: "TC-100001" });

    expect(state).toMatchObject({
      code: "gig_rejected",
      error: "Insufficient wallet balance.",
    });
    expect(revalidatePath).toHaveBeenCalledWith("/orders/TC-100001");
  });

  it("keeps capture_unconfirmed machine-readable so the panel can forbid the retry", async () => {
    mockFetch(json(
      { error: "capture_unconfirmed", detail: "The capture came back without an answer from GIG." },
      502,
    ));
    const state = await gigCaptureAction({ number: "TC-100001" });

    expect(state.code).toBe("capture_unconfirmed");
    expect(state.success).toBeUndefined();
  });
});


describe("aajCaptureAction", () => {
  it("revalidates on a refusal too — the backend just wrote it onto the timeline", async () => {
    mockFetch(json(
      { error: "create_rejected", detail: "AAJ refused the booking: name must contain only letters." },
      409,
    ));
    const state = await aajCaptureAction({ number: "TC-100001" });

    expect(state.code).toBe("create_rejected");
    expect(state.error).toMatch(/AAJ refused the booking/);
    expect(revalidatePath).toHaveBeenCalledWith("/orders/TC-100001");
  });
});
