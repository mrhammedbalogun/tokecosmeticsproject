/**
 * The server-set consent cookie (2026-09-20).
 *
 * Exists for one reason: Safari's ITP caps cookies written with `document.cookie` at 7
 * days, so 59% of this shop's buyers (iOS) were re-asked weekly whatever they clicked.
 * A server `Set-Cookie` is not capped. These tests pin the properties that make that
 * true — the lifetime, and the cookie staying readable by page JavaScript.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";

const store = new Map<string, { value: string; options: Record<string, unknown> }>();
vi.mock("next/headers", () => ({
  cookies: async () => ({
    set: (name: string, value: string, options: Record<string, unknown>) =>
      store.set(name, { value, options }),
    get: (name: string) => (store.has(name) ? { value: store.get(name)!.value } : undefined),
  }),
}));

import { POST } from "@/app/api/consent/route";
import { CONSENT_MAX_AGE } from "@/lib/consent";

const post = (body: unknown) =>
  POST(new Request("http://localhost:3000/api/consent", {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  }));

beforeEach(() => store.clear());

describe("POST /api/consent", () => {
  it("writes the choice with the full six-month lifetime", async () => {
    const res = await post({ version: 1, analytics: true, marketing: true });

    expect(res.status).toBe(200);
    const written = store.get("tc_consent")!;
    expect(JSON.parse(written.value)).toEqual({ v: 1, a: 1, m: 1 });
    // THE WHOLE POINT: 182 days, not the 7 Safari would impose on a JS-written cookie.
    expect(written.options.maxAge).toBe(CONSENT_MAX_AGE);
    expect(CONSENT_MAX_AGE).toBeGreaterThan(60 * 60 * 24 * 7);
  });

  it("leaves the cookie readable by page JavaScript", async () => {
    // Not httpOnly, deliberately: TrackingScripts decides whether to inject a pixel by
    // reading this. A consent state the browser cannot read is one it cannot honour.
    await post({ version: 1, analytics: true, marketing: true });
    expect(store.get("tc_consent")!.options.httpOnly).toBe(false);
    expect(store.get("tc_consent")!.options.sameSite).toBe("lax");
    expect(store.get("tc_consent")!.options.path).toBe("/");
  });

  it("records a refusal as a refusal", async () => {
    await post({ version: 2, analytics: false, marketing: false });
    expect(JSON.parse(store.get("tc_consent")!.value)).toEqual({ v: 2, a: 0, m: 0 });
  });

  it("records the two categories separately", async () => {
    await post({ version: 1, analytics: true, marketing: false });
    expect(JSON.parse(store.get("tc_consent")!.value)).toEqual({ v: 1, a: 1, m: 0 });
  });

  it("refuses a version that would produce a cookie decodeConsent rejects", async () => {
    // `decodeConsent` returns null for anything malformed, which re-asks — for ever.
    // `Number(null)` is 0 and 0 is the one integer that must never be written: a cookie
    // below the current version reads as unanswered, i.e. re-asks for ever.
    for (const version of ["x", null, undefined, -1, 0, 1.5]) {
      const res = await post({ version, analytics: true, marketing: true });
      expect(res.status, `version ${String(version)}`).toBe(400);
    }
    expect(store.has("tc_consent")).toBe(false);
  });

  it("treats anything but true as false rather than coercing", async () => {
    await post({ version: 1, analytics: "yes", marketing: 1 });
    expect(JSON.parse(store.get("tc_consent")!.value)).toEqual({ v: 1, a: 0, m: 0 });
  });

  it("survives a body that is not JSON at all", async () => {
    const res = await POST(new Request("http://localhost:3000/api/consent", {
      method: "POST", body: "not json",
    }));
    expect(res.status).toBe(400);
  });
});
