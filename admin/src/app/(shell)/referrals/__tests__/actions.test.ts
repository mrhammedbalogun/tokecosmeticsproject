/**
 * The payout and referrer server actions: what they send, and — the 2026-08-15 review
 * fix — what they do when the backend refuses.
 *
 * The load-bearing case is the 409: two staff working the queue at month end, B decides
 * a row, A clicks a button on the stale card. A must get the sentence AND a re-read of
 * the queue — before the fix, the action returned from its catch without revalidating,
 * so A kept a card claiming "Awaiting review" with a live Mark-paid button on it.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const store = new Map<string, string>();
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (n: string) => (store.has(n) ? { name: n, value: store.get(n) } : undefined),
    set: (n: string, v: string) => store.set(n, v),
    delete: (n: string) => store.delete(n),
  }),
}));

vi.mock("next/navigation", () => ({
  redirect: (to: string) => {
    throw new Error(`unexpected redirect to ${to}`);
  },
}));

const revalidatePath = vi.fn();
vi.mock("next/cache", () => ({ revalidatePath: (p: string) => revalidatePath(p) }));

import { approvePayoutAction, markPayoutPaidAction } from "../actions";
import { setReferrerBlockedAction } from "../referrers/actions";

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

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("a refused payout action still refreshes the queue", () => {
  it("shows the backend's 409 sentence AND revalidates, so the stale card is replaced", async () => {
    global.fetch = vi.fn(async () =>
      jsonResponse({ error: "payout_not_open", detail: "That request is no longer open." }, 409),
    ) as unknown as typeof fetch;

    const result = await approvePayoutAction({ id: 42, adminNote: "" });

    expect(result.message).toBe("That request is no longer open.");
    expect(revalidatePath).toHaveBeenCalledWith("/referrals");
  });

  it("the referrers page gets the same treatment", async () => {
    global.fetch = vi.fn(async () =>
      jsonResponse({ error: "reason_required", detail: "Say why this referrer is being blocked." }, 400),
    ) as unknown as typeof fetch;

    const result = await setReferrerBlockedAction({ id: 7, blocked: true, reason: "abuse" });

    expect(result.message).toBe("Say why this referrer is being blocked.");
    expect(revalidatePath).toHaveBeenCalledWith("/referrals/referrers");
  });
});

describe("the 403 message", () => {
  it("does not claim mark-paid is the Owner's — referrals.pay is Owner AND Manager", async () => {
    // Hammed's ruling of 2026-08-15 (rbac.py): the Manager runs the monthly transfers.
    // The old copy asserted a tighter control than exists, on the money action.
    global.fetch = vi.fn(async () =>
      jsonResponse({ detail: "You do not have permission to perform this action." }, 403),
    ) as unknown as typeof fetch;

    const result = await markPayoutPaidAction({ id: 42, reference: "GTB/1", adminNote: "" });

    expect(result.message).toMatch(/role/i);
    expect(result.message).not.toMatch(/owner/i);
  });
});

describe("the success path", () => {
  it("revalidates and reports savedAt", async () => {
    global.fetch = vi.fn(async () => jsonResponse({ id: 42, status: "approved" })) as unknown as typeof fetch;

    const result = await approvePayoutAction({ id: 42, adminNote: "" });

    expect(result.savedAt).toBeTruthy();
    expect(result.message).toBeUndefined();
    expect(revalidatePath).toHaveBeenCalledWith("/referrals");
  });
});
