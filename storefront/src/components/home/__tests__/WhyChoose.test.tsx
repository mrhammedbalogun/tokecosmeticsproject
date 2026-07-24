import { describe, it, expect, vi } from "vitest";
import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import { WhyChoose, ICONS } from "@/components/home/WhyChoose";
import { WHY_CHOOSE } from "@/lib/home-content";

vi.mock("@/components/motion/Motion", () => ({
  FadeUp: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));

describe("WhyChoose", () => {
  // The whole point of the icon/title decoupling: editing a title in
  // home-content must never blank an icon. This guards every entry.
  it("has an ICONS entry for every WHY_CHOOSE icon key", () => {
    for (const w of WHY_CHOOSE) {
      expect(ICONS, `missing icon "${w.icon}" for "${w.title}"`).toHaveProperty(w.icon);
      expect(ICONS[w.icon]).toBeTruthy();
    }
  });

  it("renders one card per pillar, each with a non-empty icon", () => {
    const { container } = render(<WhyChoose />);
    for (const w of WHY_CHOOSE) {
      expect(screen.getByRole("heading", { name: w.title })).toBeInTheDocument();
    }
    const svgs = container.querySelectorAll("svg");
    expect(svgs).toHaveLength(WHY_CHOOSE.length);
    svgs.forEach((svg) => expect(svg.children.length).toBeGreaterThan(0));
  });
});
