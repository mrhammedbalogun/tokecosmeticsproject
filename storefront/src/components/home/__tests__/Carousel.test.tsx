import { describe, it, expect, vi, beforeAll } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Carousel } from "@/components/home/Carousel";

describe("Carousel", () => {
  beforeAll(() => {
    // jsdom lacks matchMedia; the nudge() reduced-motion check needs it.
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: vi.fn().mockReturnValue({ matches: false }),
    });
  });

  it("is a labelled group with a keyboard-scrollable track and two arrow controls", () => {
    render(
      <Carousel label="Customer reviews">
        <div>slide 1</div>
        <div>slide 2</div>
      </Carousel>,
    );
    expect(screen.getByRole("group", { name: "Customer reviews" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Scroll Customer reviews back" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Scroll Customer reviews forward" }),
    ).toBeInTheDocument();
  });

  it("scrolls the track when an arrow is clicked", () => {
    render(
      <Carousel label="Best sellers">
        <div>slide</div>
      </Carousel>,
    );
    const scrollBy = vi.fn();
    // HTMLElement.scrollBy is unimplemented in jsdom.
    Element.prototype.scrollBy = scrollBy;
    fireEvent.click(screen.getByRole("button", { name: "Scroll Best sellers forward" }));
    expect(scrollBy).toHaveBeenCalledOnce();
    expect(scrollBy.mock.calls[0][0].behavior).toBe("smooth");
  });
});
