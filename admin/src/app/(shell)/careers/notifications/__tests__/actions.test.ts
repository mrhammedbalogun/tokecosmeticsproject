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

import {
  addRecipientAction,
  markConfirmedAction,
  removeRecipientAction,
  resendConfirmationAction,
  testSendAction,
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

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function form(fields: Record<string, string>): FormData {
  const data = new FormData();
  for (const [k, v] of Object.entries(fields)) data.append(k, v);
  return data;
}

const BASE = "http://backend:8000/api/v1/admin/careers/notifications/";

describe("the careers notification actions talk to the CAREERS endpoint", () => {
  it("posts to the careers-scoped URL, not the Owner-only one", async () => {
    // The whole point of the separate module: one screen is Owner-only and spans every
    // event, this one is Owner+Manager and reaches exactly one. A shared BASE constant
    // would put that permission boundary one variable away from being wrong.
    const fetchMock = vi.fn(async () => jsonResponse({ id: 1 }, 201));
    global.fetch = fetchMock as unknown as typeof fetch;

    await addRecipientAction({}, form({ kind: "external", email: "careers@toke.test" }));

    const [url] = fetchMock.mock.calls[0] as unknown as [string];
    expect(url).toBe(BASE);
    expect(url).not.toContain("notification-recipients");
  });

  it("NEVER SENDS AN EVENT, even when the shared form supplies one", async () => {
    // `NotificationSection` is written for the general screen and puts `event` in the
    // form. The backend pins it read-only; sending it anyway would be decoration that
    // looks load-bearing, and a reader could reasonably conclude the client chooses.
    const fetchMock = vi.fn(async () => jsonResponse({ id: 1 }, 201));
    global.fetch = fetchMock as unknown as typeof fetch;

    await addRecipientAction(
      {},
      form({ event: "order.paid", kind: "external", email: "sneaky@toke.test" }),
    );

    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({ email: "sneaky@toke.test" });
  });

  it("lowercases a standalone address before sending it", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ id: 2 }, 201));
    global.fetch = fetchMock as unknown as typeof fetch;

    await addRecipientAction({}, form({ kind: "external", email: "Careers@TOKE.test" }));

    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({ email: "careers@toke.test" });
  });

  it("posts a staff subscription as a user id", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ id: 3 }, 201));
    global.fetch = fetchMock as unknown as typeof fetch;

    const state = await addRecipientAction({}, form({ kind: "staff", user: "7" }));

    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({ user: 7 });
    expect(state.success).toContain("will now be emailed");
  });
});

describe("what the success message promises", () => {
  it("does NOT claim an external address is receiving anything yet", async () => {
    // It is not, and will not be until somebody clicks. Saying "will now be emailed"
    // here is the same silent-failure shape confirmation exists to remove.
    global.fetch = vi.fn(async () => jsonResponse({ id: 1 }, 201)) as unknown as typeof fetch;

    const state = await addRecipientAction(
      {},
      form({ kind: "external", email: "new@toke.test" }),
    );
    expect(state.success).toContain("Confirmation sent");
    expect(state.success).not.toContain("will now be emailed");
  });

  it("does promise it for a staff member, who is confirmed by construction", async () => {
    global.fetch = vi.fn(async () => jsonResponse({ id: 1 }, 201)) as unknown as typeof fetch;
    const state = await addRecipientAction({}, form({ kind: "staff", user: "3" }));
    expect(state.success).toContain("will now be emailed");
  });
});

describe("refusals are explained in this screen's terms", () => {
  it("a 403 blames the ROLE, not a rank — a Manager holds this screen", async () => {
    global.fetch = vi.fn(async () =>
      jsonResponse({ detail: "no" }, 403)) as unknown as typeof fetch;

    const state = await addRecipientAction(
      {},
      form({ kind: "external", email: "x@toke.test" }),
    );
    expect(state.error).toContain("Your role does not include");
    expect(state.error).not.toContain("Owner");
  });

  it("but mark-confirmed passes the BACKEND's sentence through, because 403 means something else there", async () => {
    // Vouching stays Owner-only even here: confirming reaches every pending row for the
    // address, including events this screen cannot see.
    global.fetch = vi.fn(async () =>
      jsonResponse(
        { detail: "Only the Owner can confirm an address without its own click." },
        403,
      )) as unknown as typeof fetch;

    const state = await markConfirmedAction({}, form({ recipient_id: "4" }));
    expect(state.error).toContain("Only the Owner");
  });

  it("surfaces the backend's duplicate sentence rather than a generic failure", async () => {
    global.fetch = vi.fn(async () =>
      jsonResponse({ detail: "That recipient is already on this list." }, 400),
    ) as unknown as typeof fetch;

    const state = await addRecipientAction(
      {},
      form({ kind: "external", email: "dupe@toke.test" }),
    );
    expect(state.error).toBe("That recipient is already on this list.");
  });

  it("names the throttle on a 429 rather than reporting a mystery failure", async () => {
    global.fetch = vi.fn(async () => jsonResponse({}, 429)) as unknown as typeof fetch;
    const state = await resendConfirmationAction({}, form({ recipient_id: "4" }));
    expect(state.error).toContain("Try again in a minute");
  });
});

describe("id handling", () => {
  it.each(["1e3", "0x2", "", "abc", "-1", "0", "1.0", "١٢"])(
    "refuses %o rather than addressing something else",
    async (id) => {
      // `Number()` would accept the first three and address a DIFFERENT row than the
      // one the operator clicked; `/^\d+$/` is why they never reach the network.
      const fetchMock = vi.fn();
      global.fetch = fetchMock as unknown as typeof fetch;

      const state = await removeRecipientAction({}, form({ recipient_id: id }));
      expect(state.error).toBeDefined();
      expect(fetchMock).not.toHaveBeenCalled();
    },
  );

  it("accepts a padded id, because the field reader trims before the check", async () => {
    // Not a loophole: " 1 " and "1" name the same row, and browsers do pad. Pinned so
    // the trim is a decision on the record rather than an accident of ordering.
    const fetchMock = vi.fn(async () => new Response(null, { status: 204 }));
    global.fetch = fetchMock as unknown as typeof fetch;

    const state = await removeRecipientAction({}, form({ recipient_id: " 1 " }));
    expect(state.error).toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith(`${BASE}1/`, expect.anything());
  });

  it("treats an already-gone row as the outcome the operator wanted", async () => {
    // 404 is also what this endpoint answers for a row belonging to ANOTHER event —
    // deliberately, so ids cannot be probed. Either way there is nothing to report.
    global.fetch = vi.fn(async () => jsonResponse({}, 404)) as unknown as typeof fetch;

    const state = await removeRecipientAction({}, form({ recipient_id: "9" }));
    expect(state.error).toBeUndefined();
    expect(revalidatePath).toHaveBeenCalledWith("/careers/notifications");
  });
});

describe("test-send", () => {
  it("reports the address the BACKEND says it used, never one from the form", async () => {
    global.fetch = vi.fn(async () =>
      jsonResponse({ sent_to: "real@toke.test" })) as unknown as typeof fetch;

    const state = await testSendAction(
      {},
      form({ recipient_id: "4", email: "attacker@evil.test" }),
    );
    expect(state.success).toContain("real@toke.test");
    expect(state.success).not.toContain("attacker@evil.test");
  });

  it("does not revalidate — nothing on the page changed", async () => {
    global.fetch = vi.fn(async () =>
      jsonResponse({ sent_to: "real@toke.test" })) as unknown as typeof fetch;
    await testSendAction({}, form({ recipient_id: "4" }));
    expect(revalidatePath).not.toHaveBeenCalled();
  });
});
