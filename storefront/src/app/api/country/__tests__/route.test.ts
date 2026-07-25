import { describe, it, expect, vi, beforeEach } from "vitest";

type CookieOptions = { httpOnly?: boolean; sameSite?: string; maxAge?: number };

const store = new Map<string, string>();
// The options parameter is declared (and forwarded below) precisely so the httpOnly
// assertion can read calls[0][2] — typing the spy with only two parameters made that
// index a type error while the runtime value was there all along.
const setSpy = vi.fn((n: string, v: string, _options?: CookieOptions) => store.set(n, v));
// Forward ALL args (incl. the options object) so calls[0][2] is observable.
vi.mock("next/headers", () => ({
  cookies: async () => ({
    set: (...args: unknown[]) => setSpy(...(args as [string, string, CookieOptions?])),
  }),
}));

import { POST } from "@/app/api/country/route";

beforeEach(() => { store.clear(); setSpy.mockClear(); });

describe("country set route", () => {
  it("stores an uppercased known market in the country cookie (not httpOnly)", async () => {
    const res = await POST(new Request("http://localhost:3000/api/country", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ code: "gb" }),
    }));
    expect(res.status).toBe(200);
    expect(setSpy).toHaveBeenCalled();
    expect(setSpy.mock.calls[0][0]).toBe("country");
    expect(setSpy.mock.calls[0][1]).toBe("GB");
    const options = setSpy.mock.calls[0][2];
    expect(options?.httpOnly).toBeFalsy();
  });

  it("rejects an empty code", async () => {
    const res = await POST(new Request("http://localhost:3000/api/country", {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({}),
    }));
    expect(res.status).toBe(400);
  });
});
