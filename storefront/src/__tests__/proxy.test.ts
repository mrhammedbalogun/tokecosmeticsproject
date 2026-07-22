import { describe, it, expect } from "vitest";
import { NextRequest } from "next/server";
import { proxy } from "@/proxy";

function run(headers: Record<string, string> = {}) {
  return proxy(new NextRequest("http://localhost:3000/", { headers }));
}

describe("proxy country + geo", () => {
  it("seeds the NG default cookie when none is present", () => {
    const res = run();
    expect(res.cookies.get("country")?.value).toBe("NG");
  });

  it("does not overwrite an existing country cookie", () => {
    const res = run({ cookie: "country=US" });
    // No Set-Cookie is emitted when the visitor already has a choice.
    expect(res.cookies.get("country")?.value).toBeUndefined();
  });

  it("forwards the platform geo header and ignores a client-spoofed one", () => {
    // Vercel injects x-vercel-ip-country; a client tries to spoof x-geo-country directly.
    const res = run({ "x-vercel-ip-country": "GB", "x-geo-country": "US" });
    // The forwarded (overridden) request header must reflect the trusted platform value.
    expect(res.headers.get("x-middleware-request-x-geo-country")).toBe("GB");
  });
});
