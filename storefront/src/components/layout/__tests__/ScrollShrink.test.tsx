import { describe, it, expect, afterEach } from "vitest";
import { render, act } from "@testing-library/react";
import { ScrollShrink } from "@/components/layout/ScrollShrink";

function setScrollY(y: number) {
  Object.defineProperty(window, "scrollY", { configurable: true, value: y });
}

afterEach(() => {
  setScrollY(0);
  document.documentElement.removeAttribute("data-scrolled");
});

describe("ScrollShrink", () => {
  it("does not flag data-scrolled at or below the 24px threshold", () => {
    setScrollY(24);
    render(<ScrollShrink />); // runs the scroll handler once on mount
    expect(document.documentElement.hasAttribute("data-scrolled")).toBe(false);
  });

  it("flags data-scrolled past 24px and clears it when scrolling back up", () => {
    render(<ScrollShrink />);
    setScrollY(25);
    act(() => {
      window.dispatchEvent(new Event("scroll"));
    });
    expect(document.documentElement.hasAttribute("data-scrolled")).toBe(true);

    setScrollY(10);
    act(() => {
      window.dispatchEvent(new Event("scroll"));
    });
    expect(document.documentElement.hasAttribute("data-scrolled")).toBe(false);
  });
});
