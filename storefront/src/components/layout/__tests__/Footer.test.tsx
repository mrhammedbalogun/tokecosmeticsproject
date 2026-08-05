import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Footer } from "@/components/layout/Footer";

describe("Footer (large upgrade)", () => {
  it("preserves every Plan-12 policy link to /page/[slug]", () => {
    render(<Footer />);
    const expected: [RegExp, string][] = [
      [/privacy policy/i, "/page/privacy"],
      [/terms & conditions/i, "/page/terms"],
      [/shipping & delivery/i, "/page/shipping"],
      [/returns & refunds/i, "/page/returns"],
      [/contact us/i, "/page/contact"],
    ];
    for (const [name, href] of expected) {
      expect(screen.getByRole("link", { name })).toHaveAttribute("href", href);
    }
  });

  it("renders the four link columns and a Shop → /products link", () => {
    render(<Footer />);
    for (const heading of ["Shop", "Company", "Support", "Legal"]) {
      expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument();
    }
    expect(screen.getByRole("link", { name: /all products/i })).toHaveAttribute("href", "/products");
  });

  it("closes with the centred copyright line and nothing else (Hammed, 2026-08-05)", () => {
    render(<Footer />);
    // The real © glyph, the CURRENT year (request-time, so 1 January advances it),
    // and no payment badges — those were removed with the artifact's dark footer.
    const year = new Date().getFullYear();
    const line = screen.getByText(`© Toke Cosmetics ${year}. All Rights Reserved.`);
    expect(line).toBeInTheDocument();
    expect(line).toHaveClass("text-center");
    expect(screen.queryByText("visa")).toBeNull();
    expect(screen.queryByText("bank transfer")).toBeNull();
  });

  it("exposes social profiles with accessible labels", () => {
    render(<Footer />);
    expect(screen.getByRole("link", { name: "Instagram" })).toHaveAttribute(
      "href",
      "https://www.instagram.com/tokecosmetics",
    );
  });
});
