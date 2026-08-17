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

const BASE = "http://backend:8000/api/v1/admin/notification-recipients/";

describe("addRecipientAction", () => {
  it("posts a staff subscription as a user id", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ id: 1 }, 201));
    global.fetch = fetchMock as unknown as typeof fetch;

    const state = await addRecipientAction(
      {},
      form({ event: "order.paid", kind: "staff", user: "7" }),
    );

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe(BASE);
    expect(JSON.parse(init.body as string)).toEqual({ event: "order.paid", user: 7 });
    expect(state.success).toBeDefined();
  });

  it("lowercases a standalone address before sending it", async () => {
    // The backend normalises too — this keeps the audit row and the uniqueness check
    // agreeing with what the operator sees on screen.
    const fetchMock = vi.fn(async () => jsonResponse({ id: 2 }, 201));
    global.fetch = fetchMock as unknown as typeof fetch;

    const state = await addRecipientAction(
      {},
      form({ event: "order.paid", kind: "external", email: " Packing@X.com " }),
    );

    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({
      event: "order.paid",
      email: "packing@x.com",
    });
    expect(state.success).toContain("packing@x.com");
  });

  it("honours the submitted kind rather than guessing from filled fields", async () => {
    // A browser that submits both halves (autofill, a stale form) must resolve to what
    // the operator actually clicked — not to whichever check happens to run first.
    const fetchMock = vi.fn(async () => jsonResponse({ id: 3 }, 201));
    global.fetch = fetchMock as unknown as typeof fetch;

    await addRecipientAction(
      {},
      form({ event: "order.paid", kind: "staff", user: "7", email: "stray@x.com" }),
    );

    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({ event: "order.paid", user: 7 });
  });

  it("does not call the API when no event was chosen", async () => {
    const fetchMock = vi.fn();
    global.fetch = fetchMock as unknown as typeof fetch;

    const state = await addRecipientAction({}, form({ event: "", kind: "external", email: "a@x.com" }));

    expect(fetchMock).not.toHaveBeenCalled();
    expect(state.error).toMatch(/choose a notification/i);
  });

  it("rejects a staff id that is not a plain positive integer", async () => {
    // Interpolated into a JSON body and, on the backend, a lookup. `Number()` would
    // accept "1e3", " 1 " and "0x2", each addressing something other than what was clicked.
    const fetchMock = vi.fn();
    global.fetch = fetchMock as unknown as typeof fetch;

    const state = await addRecipientAction(
      {},
      form({ event: "order.paid", kind: "staff", user: "1e3" }),
    );

    expect(fetchMock).not.toHaveBeenCalled();
    expect(state.error).toMatch(/choose a staff member/i);
  });

  it("surfaces the backend's own refusal text", async () => {
    // "That recipient is already on this list" is explained there and nowhere else.
    global.fetch = vi.fn(async () =>
      jsonResponse({ non_field_errors: ["That recipient is already on this list."] }, 400),
    ) as unknown as typeof fetch;

    const state = await addRecipientAction(
      {},
      form({ event: "order.paid", kind: "external", email: "a@x.com" }),
    );

    expect(state.error).toBe("That recipient is already on this list.");
  });

  it("explains a 403 in the page's own vocabulary", async () => {
    global.fetch = vi.fn(async () => jsonResponse({ detail: "no" }, 403)) as unknown as typeof fetch;

    const state = await addRecipientAction(
      {},
      form({ event: "order.paid", kind: "external", email: "a@x.com" }),
    );

    expect(state.error).toMatch(/only the owner/i);
  });
});

describe("removeRecipientAction", () => {
  it("deletes the row and revalidates the page", async () => {
    const fetchMock = vi.fn(async () => new Response(null, { status: 204 }));
    global.fetch = fetchMock as unknown as typeof fetch;

    const state = await removeRecipientAction({}, form({ recipient_id: "4" }));

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe(`${BASE}4/`);
    expect(init.method).toBe("DELETE");
    expect(state.error).toBeUndefined();
    expect(revalidatePath).toHaveBeenCalledWith("/notifications");
  });

  it("treats an already-deleted row as success", async () => {
    // Already gone is the state the operator wanted. An error would send somebody
    // looking for a row that is not there.
    global.fetch = vi.fn(async () => jsonResponse({ detail: "x" }, 404)) as unknown as typeof fetch;

    const state = await removeRecipientAction({}, form({ recipient_id: "4" }));

    expect(state.error).toBeUndefined();
    expect(revalidatePath).toHaveBeenCalledWith("/notifications");
  });
});

describe("testSendAction", () => {
  it("sends only the row id, never an address", async () => {
    // THE OPEN-RELAY GUARD, restated on this side: the address comes from the stored row
    // on the backend. Anything this action put in the body would be an address a caller
    // chose.
    const fetchMock = vi.fn(async () => jsonResponse({ sent_to: "pack@x.com" }));
    global.fetch = fetchMock as unknown as typeof fetch;

    const state = await testSendAction({}, form({ recipient_id: "9" }));

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe(`${BASE}test-send/`);
    expect(JSON.parse(init.body as string)).toEqual({ recipient_id: 9 });
    expect(state.success).toContain("pack@x.com");
  });

  it("does not revalidate, so the confirmation survives on screen", async () => {
    global.fetch = vi.fn(async () => jsonResponse({ sent_to: "pack@x.com" })) as unknown as typeof fetch;

    await testSendAction({}, form({ recipient_id: "9" }));

    expect(revalidatePath).not.toHaveBeenCalled();
  });

  it("surfaces a backend refusal", async () => {
    global.fetch = vi.fn(async () =>
      jsonResponse({ detail: "That staff account is no longer active, so it receives no mail." }, 400),
    ) as unknown as typeof fetch;

    const state = await testSendAction({}, form({ recipient_id: "9" }));

    expect(state.error).toMatch(/no longer active/i);
  });
});


describe("resendConfirmationAction", () => {
  it("posts only the row id to the resend endpoint", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ sent_to: "pack@x.com" }));
    global.fetch = fetchMock as unknown as typeof fetch;

    const state = await resendConfirmationAction({}, form({ recipient_id: "9" }));

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe(`${BASE}resend-confirmation/`);
    expect(JSON.parse(init.body as string)).toEqual({ recipient_id: 9 });
    expect(state.success).toContain("pack@x.com");
  });

  it("does not revalidate — the row is still pending until they click", async () => {
    global.fetch = vi.fn(async () =>
      jsonResponse({ sent_to: "pack@x.com" }),
    ) as unknown as typeof fetch;

    await resendConfirmationAction({}, form({ recipient_id: "9" }));

    expect(revalidatePath).not.toHaveBeenCalled();
  });

  it("explains a rate limit rather than showing a bare failure", async () => {
    // The endpoint is capped at 10/hour because it mails branded, official-looking post
    // to an arbitrary address on demand.
    global.fetch = vi.fn(async () =>
      jsonResponse({ detail: "throttled" }, 429),
    ) as unknown as typeof fetch;

    const state = await resendConfirmationAction({}, form({ recipient_id: "9" }));

    expect(state.error).toMatch(/too many/i);
  });

  it("surfaces the backend refusal for an already-confirmed address", async () => {
    global.fetch = vi.fn(async () =>
      jsonResponse({ detail: "That address is already confirmed." }, 400),
    ) as unknown as typeof fetch;

    const state = await resendConfirmationAction({}, form({ recipient_id: "9" }));

    expect(state.error).toBe("That address is already confirmed.");
  });
});
