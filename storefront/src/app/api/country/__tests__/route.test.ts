import { describe, it, expect, vi, beforeEach } from "vitest";

const store = new Map<string, string>();
const setSpy = vi.fn((n: string, v: string) => store.set(n, v));
// Forward ALL args (incl. the options object) so calls[0][2] is observable.
vi.mock("next/headers", () => ({
  cookies: async () => ({ set: (...args: unknown[]) => setSpy(...(args as [string, string])) }),
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
    const options = setSpy.mock.calls[0][2] as { httpOnly?: boolean };
    expect(options.httpOnly).toBeFalsy();
  });

  it("rejects an empty code", async () => {
    const res = await POST(new Request("http://localhost:3000/api/country", {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({}),
    }));
    expect(res.status).toBe(400);
  });
});
