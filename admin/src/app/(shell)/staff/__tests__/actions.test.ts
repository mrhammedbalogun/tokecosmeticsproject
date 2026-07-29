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

import { inviteAction, revokeAction } from "../actions";

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

describe("inviteAction", () => {
  it("posts the address and role to the invite endpoint", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ id: 3, email: "new@toke.test" }, 201));
    global.fetch = fetchMock as unknown as typeof fetch;

    const state = await inviteAction({}, form({ email: " New@Toke.test ", role: "Support" }));

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://backend:8000/api/v1/admin/staff/invites/");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      email: "new@toke.test",
      role: "Support",
    });
    expect(state.success).toContain("new@toke.test");
    expect(state.error).toBeUndefined();
  });

  it("refuses to call the API when a field is missing", async () => {
    // The backend would answer 400 anyway. Not calling at all keeps a mistyped form off
    // the audit trail — every reachable POST here is an attempt to mint an administrator,
    // and an empty one is noise in the one log that should be all signal.
    const fetchMock = vi.fn();
    global.fetch = fetchMock as unknown as typeof fetch;

    const state = await inviteAction({}, form({ email: "", role: "Support" }));

    expect(fetchMock).not.toHaveBeenCalled();
    expect(state.error).toMatch(/address and a role/i);
  });

  it("rejects a role that is not one of the four", async () => {
    // The dropdown offers four values; a Server Function is a public POST endpoint and
    // the dropdown is not a control. Django validates against `rbac.ROLES` as well —
    // this is the cheap half, not the real one.
    const fetchMock = vi.fn();
    global.fetch = fetchMock as unknown as typeof fetch;

    const state = await inviteAction({}, form({ email: "x@toke.test", role: "Superuser" }));

    expect(fetchMock).not.toHaveBeenCalled();
    expect(state.error).toMatch(/not a role/i);
  });

  it("surfaces the backend's own refusal message", async () => {
    // The two refusals worth reading — already staff, and a duplicate outstanding invite
    // — are both explained by Django. Replacing them with a generic message would leave
    // an Owner guessing at which of the two happened.
    global.fetch = vi.fn(async () =>
      jsonResponse({ email: ["This address already belongs to a staff account."] }, 400),
    ) as unknown as typeof fetch;

    const state = await inviteAction({}, form({ email: "owner@toke.test", role: "Support" }));

    expect(state.error).toBe("This address already belongs to a staff account.");
  });

  it("does not echo the address back into a page that never lost it", async () => {
    // The form is uncontrolled and the page re-renders on success; a `email` echo here
    // would fight the reset. Asserted so nobody adds one "for symmetry" with loginAction,
    // where the echo exists because the page is REPLACED on failure.
    global.fetch = vi.fn(async () => jsonResponse({ id: 1 }, 201)) as unknown as typeof fetch;

    const state = await inviteAction({}, form({ email: "x@toke.test", role: "Content" }));

    expect(state).not.toHaveProperty("email");
  });

  it("refreshes the staff page so the new invite appears without a manual reload", async () => {
    global.fetch = vi.fn(async () => jsonResponse({ id: 1 }, 201)) as unknown as typeof fetch;

    await inviteAction({}, form({ email: "x@toke.test", role: "Manager" }));

    expect(revalidatePath).toHaveBeenCalledWith("/staff");
  });

  it("explains a 403 as a permissions answer rather than a failure", async () => {
    global.fetch = vi.fn(async () => jsonResponse({ detail: "denied" }, 403)) as unknown as typeof fetch;

    const state = await inviteAction({}, form({ email: "x@toke.test", role: "Support" }));

    expect(state.error).toMatch(/only the owner/i);
  });
});

describe("revokeAction", () => {
  it("posts to the revoke endpoint for the given invite", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ state: "revoked" }));
    global.fetch = fetchMock as unknown as typeof fetch;

    const state = await revokeAction({}, form({ invite_id: "42" }));

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://backend:8000/api/v1/admin/staff/invites/42/revoke/");
    expect(init.method).toBe("POST");
    expect(state.error).toBeUndefined();
    expect(revalidatePath).toHaveBeenCalledWith("/staff");
  });

  it("refuses an invite id that is not a positive integer", async () => {
    // The id goes straight into a URL path. A non-numeric value cannot address an invite,
    // and building the path from it anyway is how a Server Function starts calling
    // endpoints nobody wrote.
    const fetchMock = vi.fn();
    global.fetch = fetchMock as unknown as typeof fetch;

    for (const id of ["", "abc", "-1", "1/../../orders", "1e3", "0x2", "0"]) {
      const state = await revokeAction({}, form({ invite_id: id }));
      expect(state.error).toMatch(/could not be identified/i);
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("trims surrounding whitespace rather than calling the id unidentifiable", async () => {
    // `"1 "` is a valid id with a stray space, not a hostile value — every other action
    // in this app trims its fields, and refusing here would be a confusing exception.
    const fetchMock = vi.fn(async () => jsonResponse({ state: "revoked" }));
    global.fetch = fetchMock as unknown as typeof fetch;

    const state = await revokeAction({}, form({ invite_id: " 1 " }));

    expect(state.error).toBeUndefined();
    const [url] = fetchMock.mock.calls[0] as unknown as [string];
    expect(url).toBe("http://backend:8000/api/v1/admin/staff/invites/1/revoke/");
  });
});
