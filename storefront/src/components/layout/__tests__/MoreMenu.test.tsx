import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MoreMenu } from "@/components/layout/MoreMenu";
import { MORE_LINKS } from "@/lib/site-pages";

/** The header's `More` dropdown. The behaviours pinned here are the ones that decide
 *  whether a customer can leave the menu again — a nav dropdown that traps you is worse
 *  than no dropdown. */
describe("MoreMenu", () => {
  it("starts closed, so the nav bar is not covered on load", () => {
    render(<MoreMenu />);
    expect(screen.getByRole("button", { name: /more/i })).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("link", { name: "About Us" })).toBeNull();
  });

  it("opens on click and lists every link from site-pages, in order", () => {
    render(<MoreMenu />);
    fireEvent.click(screen.getByRole("button", { name: /more/i }));
    const rendered = screen.getAllByRole("link").map((a) => a.textContent);
    expect(rendered).toEqual(MORE_LINKS.map((l) => l.label));
    // The href is what actually navigates; a correct label on a wrong href is the bug
    // this catches.
    for (const link of MORE_LINKS) {
      expect(screen.getByRole("link", { name: link.label })).toHaveAttribute("href", link.href);
    }
  });

  it("closes on Escape", () => {
    render(<MoreMenu />);
    const trigger = screen.getByRole("button", { name: /more/i });
    fireEvent.click(trigger);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("closes on a click outside itself", () => {
    render(
      <div>
        <MoreMenu />
        <button type="button">elsewhere</button>
      </div>,
    );
    const trigger = screen.getByRole("button", { name: /more/i });
    fireEvent.click(trigger);
    fireEvent.mouseDown(screen.getByRole("button", { name: "elsewhere" }));
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("closes when a link inside it is followed", () => {
    // Otherwise the panel stays open over the page the customer just navigated to —
    // client-side navigation does not unmount the header.
    render(<MoreMenu />);
    const trigger = screen.getByRole("button", { name: /more/i });
    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole("link", { name: "About Us" }));
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });
});
