import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import VerifyEmailPage, { metadata } from "../page";

const originalFetch = global.fetch;
beforeEach(() => { process.env.API_URL = "http://backend:8000"; });
afterEach(() => { global.fetch = originalFetch; vi.restoreAllMocks(); });

function visit(token?: string | string[]) {
  return VerifyEmailPage({
    searchParams: Promise.resolve(token === undefined ? {} : { token }),
  });
}

describe("verify-email page", () => {
  it("does NOT verify while rendering — it only offers a button", async () => {
    // THE point of this page. Corporate mail scanners and Outlook SafeLinks FETCH every
    // link in an email. If confirming were a side effect of rendering, a machine — not the
    // person — would satisfy the one thing email verification exists to prove, and
    // claim_legacy_orders would link past orders with nobody having asked. Verified live:
    // two GETs of a real token left email_verified_at as None.
    const f = vi.fn();
    global.fetch = f as unknown as typeof fetch;

    render(await visit("tok-123"));

    expect(f).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /confirm my email/i })).toBeInTheDocument();
  });

  it("carries the token in the form rather than acting on it", async () => {
    const { container } = render(await visit("tok-123"));
    expect(container.querySelector('input[name="token"]')).toHaveAttribute("value", "tok-123");
  });

  it("explains itself instead of offering a dead button when the token is missing", async () => {
    global.fetch = vi.fn() as unknown as typeof fetch;

    render(await visit());

    expect(screen.queryByRole("button", { name: /confirm my email/i })).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("collapses a repeated token param instead of crashing", async () => {
    const { container } = render(await visit(["tok-a", "tok-b"]));
    expect(container.querySelector('input[name="token"]')).toHaveAttribute("value", "tok-a");
  });

  it("is not indexable and does not leak the token via the referrer", async () => {
    // The token sits in the URL, so any outbound request from this page could carry it in
    // a Referer header.
    expect(metadata.robots).toMatchObject({ index: false });
    expect(metadata.referrer).toBe("no-referrer");
  });
});
