import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import ForgotPasswordPage, { metadata } from "../page";

const originalFetch = global.fetch;
beforeEach(() => {
  process.env.API_URL = "http://backend:8000";
  process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY = "0xTEST-SITE-KEY";
});
afterEach(() => {
  delete process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY;
  global.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("forgot-password page", () => {
  it("renders the email form with the Turnstile widget inside it", async () => {
    const { container } = render(await ForgotPasswordPage());
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    const widget = container.querySelector("form .cf-turnstile");
    expect(widget).not.toBeNull();
    expect(widget!.getAttribute("data-action")).toBe("turnstile-spin-v2");
  });

  it("is not indexable", async () => {
    expect(metadata.robots).toMatchObject({ index: false });
  });
});
