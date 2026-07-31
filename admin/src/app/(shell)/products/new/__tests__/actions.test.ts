import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const store = new Map<string, string>();
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (n: string) => (store.has(n) ? { name: n, value: store.get(n) } : undefined),
    set: (n: string, v: string) => store.set(n, v),
    delete: (n: string) => store.delete(n),
  }),
}));

// `redirect` works by throwing. Modelled as a thrown marker so a success can be asserted
// by its destination, and so a `redirect` swallowed by a catch block would show up as a
// test that returned a value instead of throwing.
class RedirectError extends Error {
  constructor(public to: string) {
    super(`redirect:${to}`);
  }
}
vi.mock("next/navigation", () => ({
  redirect: (to: string) => {
    throw new RedirectError(to);
  },
}));

const revalidatePath = vi.fn();
vi.mock("next/cache", () => ({ revalidatePath: (p: string) => revalidatePath(p) }));

import { createProductAction } from "../actions";

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

/** Runs the action and returns either the state it returned or the redirect it threw. */
async function run(fields: Record<string, string>) {
  try {
    const state = await createProductAction({}, form(fields));
    return { state, redirectedTo: null as string | null };
  } catch (e) {
    if (e instanceof RedirectError) return { state: null, redirectedTo: e.to };
    throw e;
  }
}

describe("createProductAction", () => {
  it("posts the name and slug and lands on the editor", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ slug: "carrot-shea-butter" }, 201));
    global.fetch = fetchMock as unknown as typeof fetch;

    const { redirectedTo } = await run({ name: "Carrot Shea Butter", slug: "carrot-shea-butter" });

    expect(redirectedTo).toBe("/products/carrot-shea-butter");
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://backend:8000/api/v1/admin/products/");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      name: "Carrot Shea Butter",
      slug: "carrot-shea-butter",
    });
  });

  it("SENDS NO STATUS, so the model's `draft` default applies", async () => {
    // A product created straight to `active` would be one with no price, no image and no
    // copy. The Details tab publishes it when it is ready.
    const fetchMock = vi.fn(async () => jsonResponse({ slug: "x" }, 201));
    global.fetch = fetchMock as unknown as typeof fetch;

    await run({ name: "X", slug: "x" });

    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(init.body as string)).not.toHaveProperty("status");
  });

  it("follows the slug the BACKEND returned, not the one submitted", async () => {
    // The backend may normalise it, and the redirect must go where the record actually is.
    global.fetch = vi.fn(async () => jsonResponse({ slug: "normalised" }, 201)) as never;

    const { redirectedTo } = await run({ name: "Whatever", slug: "submitted" });

    expect(redirectedTo).toBe("/products/normalised");
  });

  it("fills an empty slug from the name rather than refusing", async () => {
    // Clearing the field means "you choose", not "fail".
    const fetchMock = vi.fn(async () => jsonResponse({ slug: "kids-shampoo" }, 201));
    global.fetch = fetchMock as unknown as typeof fetch;

    await run({ name: "Kids Shampoo", slug: "" });

    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(init.body as string).slug).toBe("kids-shampoo");
  });

  it("refuses a nameless product without calling the API", async () => {
    const fetchMock = vi.fn();
    global.fetch = fetchMock as unknown as typeof fetch;

    const { state } = await run({ name: "", slug: "" });

    expect(state?.fieldErrors?.name).toBeDefined();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("asks for a slug when the name produces none", async () => {
    // A name of only punctuation slugifies to "" — reachable, not theoretical.
    const fetchMock = vi.fn();
    global.fetch = fetchMock as unknown as typeof fetch;

    const { state } = await run({ name: "!!!", slug: "" });

    expect(state?.fieldErrors?.slug).toBeDefined();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("refuses a slug that would not survive being put in a URL path", async () => {
    const fetchMock = vi.fn();
    global.fetch = fetchMock as unknown as typeof fetch;

    const { state } = await run({ name: "Fine", slug: "not a slug/at all" });

    expect(state?.fieldErrors?.slug).toMatch(/letters, numbers/i);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("SURFACES THE BACKEND'S OWN COLLISION MESSAGE, verbatim", async () => {
    // The spec forbids a client-side uniqueness check: only the database knows whether a
    // slug is free, and its sentence is both accurate and specific.
    global.fetch = vi.fn(async () =>
      jsonResponse({ slug: ["product with this slug already exists."] }, 400),
    ) as never;

    const { state } = await run({ name: "Dupe", slug: "carrot-shea-butter" });

    expect(state?.fieldErrors?.slug).toBe("product with this slug already exists.");
  });

  it("puts a non-field 400 in the banner rather than dropping it", async () => {
    global.fetch = vi.fn(async () =>
      jsonResponse({ non_field_errors: ["That combination is taken."] }, 400),
    ) as never;

    const { state } = await run({ name: "X", slug: "x" });

    expect(state?.error).toBe("That combination is taken.");
  });

  it("explains a 403 instead of reporting a generic failure", async () => {
    global.fetch = vi.fn(async () => jsonResponse({ detail: "No." }, 403)) as never;

    const { state } = await run({ name: "X", slug: "x" });

    expect(state?.error).toMatch(/role does not include/i);
  });

  it("echoes what was typed so a rejected form does not empty itself", async () => {
    global.fetch = vi.fn(async () => jsonResponse({ slug: ["taken"] }, 400)) as never;

    const { state } = await run({ name: "Carrot Shea", slug: "carrot-shea" });

    expect(state?.values).toEqual({ name: "Carrot Shea", slug: "carrot-shea" });
  });

  it("revalidates the products list on success", async () => {
    global.fetch = vi.fn(async () => jsonResponse({ slug: "x" }, 201)) as never;

    await run({ name: "X", slug: "x" });

    expect(revalidatePath).toHaveBeenCalledWith("/products");
  });

  it("does not revalidate when the create failed", async () => {
    global.fetch = vi.fn(async () => jsonResponse({ slug: ["taken"] }, 400)) as never;

    await run({ name: "X", slug: "x" });

    expect(revalidatePath).not.toHaveBeenCalled();
  });
});
