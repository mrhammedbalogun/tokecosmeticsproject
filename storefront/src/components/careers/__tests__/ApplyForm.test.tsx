import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ApplyForm } from "@/components/careers/ApplyForm";
import type { Job } from "@/lib/careers";

// The Turnstile widget renders nothing without a site key and loads a third-party
// script; stubbed so these tests are about the form.
vi.mock("@/components/auth/TurnstileWidget", () => ({
  TurnstileWidget: () => null,
  turnstileToken: () => "test-token",
}));

function job(overrides: Partial<Job> = {}): Job {
  return {
    slug: "sales-representative",
    title: "Sales Representative",
    department: "Sales",
    employment_type: "full_time",
    employment_type_label: "Full-Time",
    workplace_type: "on_site",
    workplace_type_label: "On-site",
    country_name: "Nigeria",
    country_code: "NG",
    compensation_text: "Good Pay",
    summary: "",
    description: "",
    requirements: "",
    locations: [],
    status: "open",
    is_accepting: true,
    published_at: null,
    closes_at: null,
    ...overrides,
  };
}

function pdf(name = "CV.pdf", size = 1024): File {
  const f = new File(["%PDF-1.4"], name, { type: "application/pdf" });
  Object.defineProperty(f, "size", { value: size });
  return f;
}

/** The two-step upload uses XHR (for progress events), which jsdom does not implement
 *  usefully. This stands in for it and reports success immediately. */
class FakeXhr {
  upload = { onprogress: null as ((e: ProgressEvent) => void) | null };
  status = 204;
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  open() {}
  send() {
    this.upload.onprogress?.({ lengthComputable: true, loaded: 5, total: 10 } as ProgressEvent);
    this.onload?.();
  }
}

beforeEach(() => {
  vi.stubGlobal("XMLHttpRequest", FakeXhr as unknown as typeof XMLHttpRequest);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function mockApi(responses: { ticket?: Response; apply?: Response } = {}) {
  const calls: { url: string; body: unknown }[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    calls.push({ url, body: init?.body ? JSON.parse(String(init.body)) : null });
    if (url.includes("/careers/uploads/")) {
      return (
        responses.ticket ??
        new Response(
          JSON.stringify({ mode: "s3", url: "https://s3.test/", fields: {}, key: "incoming/k.pdf" }),
          { status: 201, headers: { "content-type": "application/json" } },
        )
      );
    }
    return (
      responses.apply ??
      new Response(JSON.stringify({ job_title: "Sales Representative" }), {
        status: 201,
        headers: { "content-type": "application/json" },
      })
    );
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

function fill() {
  fireEvent.change(screen.getByLabelText("Full name"), { target: { value: "Ada Obi" } });
  fireEvent.change(screen.getByLabelText("Email address"), {
    target: { value: "ada@example.com" },
  });
  fireEvent.change(screen.getByLabelText<HTMLInputElement>(/Your CV/), {
    target: { files: [pdf()] },
  });
}

describe("the apply form", () => {
  it("refuses a wrong file type without uploading anything", () => {
    const calls = mockApi();
    render(<ApplyForm job={job()} />);

    fireEvent.change(screen.getByLabelText<HTMLInputElement>(/Your CV/), {
      target: { files: [new File(["MZ"], "payload.exe")] },
    });

    expect(screen.getByText(/PDF, DOC or DOCX file/)).toBeTruthy();
    expect(calls).toHaveLength(0);
  });

  it("refuses a file over 5MB without uploading it", () => {
    const calls = mockApi();
    render(<ApplyForm job={job()} />);

    fireEvent.change(screen.getByLabelText<HTMLInputElement>(/Your CV/), {
      target: { files: [pdf("CV.pdf", 6 * 1024 * 1024)] },
    });

    expect(screen.getByText(/larger than 5MB/)).toBeTruthy();
    expect(calls).toHaveLength(0);
  });

  it("uploads then submits, and confirms without promising a deadline", async () => {
    const calls = mockApi();
    render(<ApplyForm job={job()} />);
    fill();
    fireEvent.submit(screen.getByRole("button", { name: /Submit application/ }).closest("form")!);

    await waitFor(() => expect(screen.getByText("Application received")).toBeTruthy());
    expect(calls[0].url).toContain("/api/v1/careers/uploads/");
    expect(calls[1].url).toContain("/careers/jobs/sales-representative/apply/");
    const body = calls[1].body as Record<string, unknown>;
    expect(body.upload_key).toBe("incoming/k.pdf");
    expect(body.full_name).toBe("Ada Obi");
    // The honeypot is always sent, and always empty for a human.
    expect(body.website).toBe("");
  });

  it("shows a field error the backend named, against that field", async () => {
    mockApi({
      apply: new Response(JSON.stringify({ phone: ["Include the country code."] }), {
        status: 400,
        headers: { "content-type": "application/json" },
      }),
    });
    render(<ApplyForm job={job()} />);
    fill();
    fireEvent.submit(screen.getByRole("button", { name: /Submit application/ }).closest("form")!);

    await waitFor(() => expect(screen.getByText("Include the country code.")).toBeTruthy());
    expect(screen.getByRole("alert").textContent).toMatch(/check the highlighted fields/i);
  });

  it("DOES NOT RE-UPLOAD THE CV after a failure that was not about the file", async () => {
    // A 5MB CV on a mobile connection is thirty seconds. Re-uploading it because the
    // phone number was malformed is the difference between one wait and two.
    const calls = mockApi({
      apply: new Response(JSON.stringify({ phone: ["Include the country code."] }), {
        status: 400,
        headers: { "content-type": "application/json" },
      }),
    });
    render(<ApplyForm job={job()} />);
    fill();
    const form = screen.getByRole("button", { name: /Submit application/ }).closest("form")!;

    fireEvent.submit(form);
    await waitFor(() => expect(screen.getByText("Include the country code.")).toBeTruthy());
    fireEvent.submit(form);
    await waitFor(() => expect(calls.length).toBeGreaterThan(2));

    const ticketCalls = calls.filter((c) => c.url.includes("/careers/uploads/"));
    expect(ticketCalls).toHaveLength(1);
  });

  it("clears the stored upload when the backend rejected the FILE", async () => {
    const calls = mockApi({
      apply: new Response(JSON.stringify({ resume: ["That file is not a valid PDF."] }), {
        status: 400,
        headers: { "content-type": "application/json" },
      }),
    });
    render(<ApplyForm job={job()} />);
    fill();
    fireEvent.submit(screen.getByRole("button", { name: /Submit application/ }).closest("form")!);

    await waitFor(() => expect(screen.getByText("That file is not a valid PDF.")).toBeTruthy());
    // The file is dropped, so the next attempt cannot silently re-send bytes the backend
    // has already refused.
    expect(screen.getByText(/Drop your CV here/)).toBeTruthy();
    expect(calls.filter((c) => c.url.includes("/careers/uploads/"))).toHaveLength(1);
  });

  it("reports a closed role as a sentence rather than a field error", async () => {
    mockApi({
      apply: new Response(
        JSON.stringify({ detail: "This role is no longer accepting applications." }),
        { status: 409, headers: { "content-type": "application/json" } },
      ),
    });
    render(<ApplyForm job={job()} />);
    fill();
    fireEvent.submit(screen.getByRole("button", { name: /Submit application/ }).closest("form")!);

    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toMatch(/no longer accepting/),
    );
  });

  it("asks which location when the role lists several, and sends the choice", async () => {
    const calls = mockApi();
    render(
      <ApplyForm
        job={job({ locations: [{ id: 7, label: "Enugu" }, { id: 8, label: "Abuja" }] })}
      />,
    );
    fill();
    fireEvent.change(screen.getByLabelText(/Which location/), { target: { value: "8" } });
    fireEvent.submit(screen.getByRole("button", { name: /Submit application/ }).closest("form")!);

    await waitFor(() => expect(screen.getByText("Application received")).toBeTruthy());
    expect((calls[1].body as Record<string, unknown>).location).toBe(8);
  });

  it("does not ask for a location when the role has none", () => {
    mockApi();
    render(<ApplyForm job={job()} />);
    expect(screen.queryByLabelText(/Which location/)).toBeNull();
  });
});
