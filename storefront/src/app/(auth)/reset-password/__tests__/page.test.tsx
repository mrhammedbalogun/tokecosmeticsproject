import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import ResetPasswordPage, { metadata } from "../page";

const originalFetch = global.fetch;
beforeEach(() => { process.env.API_URL = "http://backend:8000"; });
afterEach(() => { global.fetch = originalFetch; vi.restoreAllMocks(); });

function visit(params: Record<string, string | string[]> = {}) {
  return ResetPasswordPage({ searchParams: Promise.resolve(params) });
}

describe("reset-password page", () => {
  it("renders the new-password form with uid and token carried as hidden inputs", async () => {
    const { container } = render(await visit({ uid: "MTI", token: "tok-abc" }));
    expect(container.querySelector('input[name="uid"]')).toHaveAttribute("value", "MTI");
    expect(container.querySelector('input[name="token"]')).toHaveAttribute("value", "tok-abc");
    expect(screen.getByLabelText(/^new password$/i)).toBeInTheDocument();
  });

  it("explains itself instead of offering a dead form when the link is incomplete", async () => {
    render(await visit({ uid: "MTI" })); // token missing
    expect(screen.queryByLabelText(/^new password$/i)).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("collapses repeated params instead of crashing", async () => {
    const { container } = render(await visit({ uid: ["a", "b"], token: ["t1", "t2"] }));
    expect(container.querySelector('input[name="uid"]')).toHaveAttribute("value", "a");
  });

  it("is not indexable and does not leak the token via the referrer", async () => {
    // The reset token sits in the URL; an outbound request could carry it in Referer.
    expect(metadata.robots).toMatchObject({ index: false });
    expect(metadata.referrer).toBe("no-referrer");
  });
});
