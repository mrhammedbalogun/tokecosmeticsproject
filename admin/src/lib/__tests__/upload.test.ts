import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { uploadToS3 } from "@/lib/upload";

class FakeXHR {
  static last: FakeXHR;
  upload = { onprogress: null as null | ((e: ProgressEvent) => void) };
  onload: null | (() => void) = null;
  onerror: null | (() => void) = null;
  onabort: null | (() => void) = null;
  status = 204;
  responseText = "";
  sent: FormData | null = null;
  aborted = false;
  constructor() { FakeXHR.last = this; }
  open() {}
  send(body: FormData) { this.sent = body; }
  abort() { this.aborted = true; this.onabort?.(); }
}

beforeEach(() => { vi.stubGlobal("XMLHttpRequest", FakeXHR); });
afterEach(() => { vi.unstubAllGlobals(); });

const ticket = { url: "https://s3.example/bucket", fields: { key: "incoming/a.mp4", policy: "p" }, key: "incoming/a.mp4" };
const file = new File(["xyz"], "a.mp4", { type: "video/mp4" });

describe("uploadToS3", () => {
  it("posts every policy field before the file, which S3 requires", async () => {
    const handle = uploadToS3(ticket, file, () => {});
    FakeXHR.last.onload!();
    await handle.promise;

    const keys = [...(FakeXHR.last.sent as FormData).keys()];
    expect(keys).toEqual(["key", "policy", "file"]);
  });

  it("reports progress as a percentage", async () => {
    const seen: number[] = [];
    const handle = uploadToS3(ticket, file, (pct) => seen.push(pct));
    FakeXHR.last.upload.onprogress!({ lengthComputable: true, loaded: 25, total: 100 } as ProgressEvent);
    FakeXHR.last.upload.onprogress!({ lengthComputable: true, loaded: 100, total: 100 } as ProgressEvent);
    FakeXHR.last.onload!();
    await handle.promise;

    expect(seen).toEqual([25, 100]);
  });

  it("rejects with S3's status when the policy is refused", async () => {
    const handle = uploadToS3(ticket, file, () => {});
    FakeXHR.last.status = 403;
    FakeXHR.last.responseText = "<Error><Code>EntityTooLarge</Code></Error>";
    FakeXHR.last.onload!();

    await expect(handle.promise).rejects.toThrow(/EntityTooLarge/);
  });

  it("rejects on a network drop rather than hanging forever", async () => {
    const handle = uploadToS3(ticket, file, () => {});
    FakeXHR.last.onerror!();
    await expect(handle.promise).rejects.toThrow(/connection/i);
  });

  it("can be aborted", async () => {
    const handle = uploadToS3(ticket, file, () => {});
    handle.abort();
    await expect(handle.promise).rejects.toThrow(/cancelled/i);
    expect(FakeXHR.last.aborted).toBe(true);
  });
});
