import { describe, it, expect, vi, beforeAll, afterAll } from "vitest";
import { render, screen } from "@testing-library/react";
import { Carousel } from "@/components/home/Carousel";

/** jsdom has no layout, so scrollWidth/clientWidth are 0 (→ not overflowing, arrows
 * hidden). These getters simulate a track wider than its viewport, scrolled to the
 * start, so the arrows render with the back arrow disabled and forward enabled. */
function stubGeometry({ scrollWidth = 1000, clientWidth = 300, scrollLeft = 0 } = {}) {
  const defs = { scrollWidth, clientWidth, scrollLeft };
  for (const [k, v] of Object.entries(defs)) {
    Object.defineProperty(HTMLElement.prototype, k, { configurable: true, get: () => v });
  }
}

describe("Carousel", () => {
  const scrollBy = vi.fn();
  beforeAll(() => {
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: vi.fn().mockReturnValue({ matches: false }),
    });
    // HTMLElement.prototype.scrollBy is unimplemented in jsdom.
    Element.prototype.scrollBy = scrollBy;
  });
  afterAll(() => {
    for (const k of ["scrollWidth", "clientWidth", "scrollLeft"]) {
      delete (HTMLElement.prototype as unknown as Record<string, unknown>)[k];
    }
  });

  it("names both the group and the keyboard-scrollable track", () => {
    stubGeometry();
    render(
      <Carousel label="Customer reviews">
        <div>slide 1</div>
        <div>slide 2</div>
      </Carousel>,
    );
    // group (outer) + track (focusable div) both carry the accessible name.
    expect(screen.getAllByRole("group", { name: "Customer reviews" }).length).toBeGreaterThan(0);
    const track = document.querySelector('[tabindex="0"]');
    expect(track).toHaveAttribute("aria-label", "Customer reviews");
  });

  it("shows arrows when overflowing, disables the back arrow at the start", () => {
    stubGeometry({ scrollLeft: 0 });
    render(
      <Carousel label="Best sellers">
        <div>slide</div>
      </Carousel>,
    );
    expect(screen.getByRole("button", { name: "Scroll Best sellers back" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Scroll Best sellers forward" })).toBeEnabled();
  });

  it("scrolls smoothly when an enabled arrow is clicked", () => {
    stubGeometry({ scrollLeft: 0 });
    render(
      <Carousel label="Rows">
        <div>slide</div>
      </Carousel>,
    );
    scrollBy.mockClear();
    screen.getByRole("button", { name: "Scroll Rows forward" }).click();
    expect(scrollBy).toHaveBeenCalledOnce();
    expect(scrollBy.mock.calls[0][0].behavior).toBe("smooth");
  });

  it("hides arrows entirely when the track does not overflow", () => {
    stubGeometry({ scrollWidth: 300, clientWidth: 300 });
    render(
      <Carousel label="Short">
        <div>only slide</div>
      </Carousel>,
    );
    expect(screen.queryByRole("button", { name: /Scroll Short/ })).toBeNull();
  });
});
