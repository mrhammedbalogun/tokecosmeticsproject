import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { FlutterwaveLaunch } from "@/components/checkout/FlutterwaveLaunch";

const assign = vi.fn();
beforeEach(() => {
  assign.mockClear();
  Object.defineProperty(window, "location", { value: { assign }, writable: true });
});
afterEach(() => vi.restoreAllMocks());

describe("FlutterwaveLaunch", () => {
  it("redirects to the hosted page on mount", () => {
    render(<FlutterwaveLaunch data={{ redirect_url: "https://flw/pay/abc" }} />);
    expect(assign).toHaveBeenCalledWith("https://flw/pay/abc");
  });
  it("shows a retryable error and does not navigate when redirect_url is missing", () => {
    render(<FlutterwaveLaunch data={{}} />);
    expect(assign).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });
});
