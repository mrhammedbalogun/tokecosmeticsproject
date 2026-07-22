import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { POST } from "@/app/api/newsletter/route";

const originalFetch = global.fetch;
beforeEach(() => { process.env.API_URL = "http://backend:8000"; });
afterEach(() => { global.fetch = originalFetch; vi.restoreAllMocks(); });

function upstream(status: number, body: unknown) {
  const f = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }),
  );
  global.fetch = f as unknown as typeof fetch;
  return f;
}
function req(body: unknown, ip = "1.2.3.4") {
  return new Request("http://localhost:3000/api/newsletter", {
    method: "POST",
    headers: { "content-type": "application/json", "x-forwarded-for": ip },
    body: JSON.stringify(body),
  });
}

describe("newsletter BFF", () => {
  it("proxies a subscribe to Django and forwards the client IP", async () => {
    const f = upstream(201, { detail: "Subscribed." });
    const res = await POST(req({ email: "a@b.com", source: "footer" }));
    expect(res.status).toBe(201);
    const url = f.mock.calls[0][0] as string;
    expect(url).toBe("http://backend:8000/api/v1/newsletter/");
    const init = f.mock.calls[0][1] as RequestInit;
    expect(new Headers(init.headers).get("X-Forwarded-For")).toBe("1.2.3.4");
  });

  it("passes through a 429 throttle response", async () => {
    upstream(429, { detail: "Request was throttled." });
    const res = await POST(req({ email: "a@b.com" }));
    expect(res.status).toBe(429);
  });

  it("rejects a missing email locally with 400 (no upstream call)", async () => {
    const f = upstream(201, {});
    const res = await POST(req({}));
    expect(res.status).toBe(400);
    expect(f).not.toHaveBeenCalled();
  });
});
