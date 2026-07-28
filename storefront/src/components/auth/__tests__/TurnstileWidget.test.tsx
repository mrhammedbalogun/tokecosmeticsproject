import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";
import { TurnstileWidget } from "../TurnstileWidget";

const SITE_KEY = "0xTEST-SITE-KEY";

declare global {
  interface Window {
    turnstile?: { reset: (id?: string) => void; getResponse: (id?: string) => string };
  }
}

beforeEach(() => {
  process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY = SITE_KEY;
});
afterEach(() => {
  delete process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY;
  delete window.turnstile;
  cleanup();
});

describe("TurnstileWidget", () => {
  it("renders the cf-turnstile container with the Spin telemetry marker", () => {
    const { container } = render(<TurnstileWidget />);
    const div = container.querySelector(".cf-turnstile");
    expect(div).not.toBeNull();
    expect(div!.getAttribute("data-sitekey")).toBe(SITE_KEY);
    // Required by the Spin integration contract — analytics attribution only,
    // the widget works without it, so a test is what keeps it from vanishing.
    expect(div!.getAttribute("data-action")).toBe("turnstile-spin-v2");
  });

  it("renders nothing when the site key is not configured (gate-off deploys)", () => {
    delete process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY;
    const { container } = render(<TurnstileWidget />);
    expect(container.querySelector(".cf-turnstile")).toBeNull();
  });

  it("resets the widget when resetSignal changes, but not on first render", () => {
    // Tokens are single-use: after a failed submit the DOM still holds the
    // redeemed token, and a naive retry gets rejected as timeout-or-duplicate.
    const reset = vi.fn();
    window.turnstile = { reset, getResponse: () => "" };

    const first = { error: "bad password" };
    const { rerender } = render(<TurnstileWidget resetSignal={first} />);
    expect(reset).not.toHaveBeenCalled();

    rerender(<TurnstileWidget resetSignal={{ error: "still bad" }} />);
    expect(reset).toHaveBeenCalledTimes(1);

    rerender(<TurnstileWidget resetSignal={{ error: "third time" }} />);
    expect(reset).toHaveBeenCalledTimes(2);
  });
});
