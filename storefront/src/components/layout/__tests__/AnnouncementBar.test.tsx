import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { AnnouncementBar } from "@/components/layout/AnnouncementBar";
import { ANNOUNCEMENTS } from "@/lib/home-content";

/** The marquee (landing redesign): a CSS-animated track, so behaviour tests are
 * structural — the loop needs two copies, links need hrefs, fallback needs the
 * fixtures. The scroll/pause/reduced-motion behaviour itself is CSS, exercised
 * by the browser walkthrough, not by JSDOM. */
describe("AnnouncementBar marquee", () => {
  it("renders every item twice for the seamless loop, second copy aria-hidden", () => {
    render(
      <AnnouncementBar
        items={[
          { text: "Free delivery to the UK", url: "" },
          { text: "Now shipping worldwide", url: "/pages/shipping" },
        ]}
      />,
    );
    expect(screen.getAllByText("Free delivery to the UK")).toHaveLength(2);
    const linked = screen.getAllByRole("link", { name: "Now shipping worldwide" });
    // Only the first copy is exposed to assistive tech; both link for the loop.
    expect(linked).toHaveLength(1);
    expect(linked[0]).toHaveAttribute("href", "/pages/shipping");
  });

  it("items without a URL are plain text, not empty links", () => {
    render(<AnnouncementBar items={[{ text: "We are open Mon-Sat", url: "" }]} />);
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getAllByText("We are open Mon-Sat").length).toBeGreaterThan(0);
  });

  it("falls back to the Plan-13 fixtures when the CMS is empty", () => {
    render(<AnnouncementBar />);
    expect(screen.getAllByText(ANNOUNCEMENTS[0]).length).toBeGreaterThan(0);
  });
});
