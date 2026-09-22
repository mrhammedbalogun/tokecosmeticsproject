/**
 * The programme data layer's two judgement calls, pinned.
 *
 * Both are about what happens when the backend is NOT answering, which is the only
 * interesting state this module has — the happy path is a fetch and a cast.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ApplyError,
  getProgrammeConfig,
  submitApplication,
} from "@/lib/entrepreneurship";

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
}));

import { apiFetch } from "@/lib/api";

const mockApiFetch = vi.mocked(apiFetch);

afterEach(() => {
  vi.restoreAllMocks();
  mockApiFetch.mockReset();
});

describe("getProgrammeConfig fails OPEN", () => {
  it("shows the form when the API is unreachable", async () => {
    mockApiFetch.mockRejectedValue(new Error("boom"));

    const config = await getProgrammeConfig();

    // THE JUDGEMENT CALL. Failing closed would turn any backend blip into "this
    // programme is not accepting applications" — a lie told to a real student, who then
    // leaves. The submit is re-checked server-side, so the worst case this way is a
    // wasted form fill and the worst case the other way is a lost applicant.
    expect(config.is_open).toBe(true);
    expect(config.countries.length).toBeGreaterThan(0);
  });

  it("never renders an empty country dropdown", async () => {
    // A half-deployed backend answering `{is_open: true}` and nothing else must not
    // produce a select with no options in it.
    mockApiFetch.mockResolvedValue({ is_open: true } as never);

    const config = await getProgrammeConfig();

    expect(config.countries.map((c) => c.code)).toContain("NG");
    expect(config.closed_message.length).toBeGreaterThan(20);
  });

  it("honours a real closed answer", async () => {
    mockApiFetch.mockResolvedValue({
      is_open: false,
      closed_message: "Back in January.",
      countries: [{ code: "NG", name: "Nigeria" }],
    } as never);

    const config = await getProgrammeConfig();

    expect(config.is_open).toBe(false);
    expect(config.closed_message).toBe("Back in January.");
  });
});

describe("submitApplication maps the refusals a student can actually hit", () => {
  const draft = {
    country: "NG",
    full_name: "Chidinma Eze",
    email: "chidinma@example.com",
    phone: "+2348023900964",
    institution: "University of Lagos",
    academic_level: "300 Level",
    course_of_study: "Biochemistry",
    social_handle: "",
    motivation: "",
    website: "",
  };

  function reply(status: number, body: unknown) {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: status >= 200 && status < 300,
        status,
        json: async () => body,
      }),
    );
  }

  it("flags a 409 as the intake closing rather than as a field error", async () => {
    // Its own flag because it is NOT something the student can fix by editing a field,
    // and "check the highlighted fields" when there is nothing to fix is how a form
    // makes somebody try four more times.
    reply(409, { detail: "Applications reopen in January." });

    const error = await submitApplication(draft).catch((e) => e);

    expect(error).toBeInstanceOf(ApplyError);
    expect(error.intakeClosed).toBe(true);
    expect(error.message).toBe("Applications reopen in January.");
  });

  it("keys DRF field errors by field so the form can paint them", async () => {
    reply(400, { phone: ["Enter the number in full, including the country code."] });

    const error = await submitApplication(draft).catch((e) => e);

    expect(error.intakeClosed).toBe(false);
    expect(error.fieldErrors.phone).toContain("country code");
  });

  it("explains a throttle instead of reporting a generic failure", async () => {
    reply(429, {});
    const error = await submitApplication(draft).catch((e) => e);
    expect(error.message).toMatch(/wait a minute/i);
  });

  it("explains a Turnstile refusal without accusing anybody", async () => {
    reply(403, {});
    const error = await submitApplication(draft).catch((e) => e);
    expect(error.message).toMatch(/refresh the page/i);
  });

  it("separates a dead network from a refusing server", async () => {
    // A thrown `fetch` is the connection, not us — and "check your connection" is
    // actionable in a way that "something went wrong" is not.
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("network")));

    const error = await submitApplication(draft).catch((e) => e);

    expect(error).toBeInstanceOf(ApplyError);
    expect(error.message).toMatch(/connection/i);
  });

  it("resolves quietly on success", async () => {
    reply(201, { full_name: "Chidinma Eze" });
    await expect(submitApplication(draft)).resolves.toBeUndefined();
  });
});
