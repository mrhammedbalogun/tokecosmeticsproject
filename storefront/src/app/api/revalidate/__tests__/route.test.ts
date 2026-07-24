import { describe, it, expect, vi, beforeEach } from "vitest";

const revalidateTag = vi.fn();
vi.mock("next/cache", () => ({ revalidateTag: (t: string) => revalidateTag(t) }));

import { POST } from "@/app/api/revalidate/route";

const req = (body: unknown, secret?: string) =>
  new Request("http://localhost:3000/api/revalidate", {
    method: "POST",
    headers: { "content-type": "application/json",
               ...(secret ? { "x-revalidate-secret": secret } : {}) },
    body: JSON.stringify(body),
  });

describe("revalidate route", () => {
  beforeEach(() => { process.env.REVALIDATE_SECRET = "s3cret"; revalidateTag.mockClear(); });

  it("revalidates the given tags with the right secret", async () => {
    const res = await POST(req({ tags: ["catalog", "product:serum"] }, "s3cret"));
    expect(res.status).toBe(200);
    expect(revalidateTag).toHaveBeenCalledWith("catalog");
    expect(revalidateTag).toHaveBeenCalledWith("product:serum");
  });
  it("401 on a wrong/missing secret, nothing revalidated", async () => {
    const res = await POST(req({ tags: ["catalog"] }, "wrong"));
    expect(res.status).toBe(401);
    expect(revalidateTag).not.toHaveBeenCalled();
  });
  it("400 when tags is not a non-empty string array", async () => {
    const res = await POST(req({ tags: [] }, "s3cret"));
    expect(res.status).toBe(400);
  });
});
