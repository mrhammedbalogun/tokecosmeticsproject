/** The 2026-08-11 homepage-invisible regression, pinned: FadeUp content must be
 * present and NOT opacity-hidden in the pre-mount (i.e. server) markup — a page
 * where hydration fails has to fail toward "no animation", never "no content". */
import { beforeAll, describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { render, screen } from "@testing-library/react";
import { FadeUp, MotionRoot } from "@/components/motion/Motion";

beforeAll(() => {
  // jsdom has no IntersectionObserver; framer's whileInView needs one the moment
  // the hydrated m.div mounts.
  vi.stubGlobal("IntersectionObserver", class {
    observe() {}
    unobserve() {}
    disconnect() {}
  });
});

describe("FadeUp", () => {
  it("server markup carries the content visible (no opacity:0 initial state)", () => {
    const html = renderToStaticMarkup(
      <MotionRoot>
        <FadeUp>
          <p>Shop by Category</p>
        </FadeUp>
      </MotionRoot>
    );
    expect(html).toContain("Shop by Category");
    expect(html).not.toMatch(/opacity:\s*0/);
  });

  it("renders children after mount too (the animated path)", () => {
    render(
      <MotionRoot>
        <FadeUp>
          <p>Made for every one of you</p>
        </FadeUp>
      </MotionRoot>
    );
    expect(screen.getByText("Made for every one of you")).toBeInTheDocument();
  });
});
