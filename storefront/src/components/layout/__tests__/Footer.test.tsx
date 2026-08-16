import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Footer } from "@/components/layout/Footer";

describe("Footer (large upgrade)", () => {
  it("preserves the Plan-12 policy links that are still CMS pages", () => {
    render(<Footer />);
    // These four remain `/page/[slug]` because they are policy text a Content editor
    // owns. THEY 404 IN PRODUCTION TODAY — `GET /cms/pages/` returns `[]`, so the rows
    // were never written. The links are correct; the content is missing.
    const expected: [RegExp, string][] = [
      [/privacy policy/i, "/page/privacy"],
      [/terms & conditions/i, "/page/terms"],
      [/shipping & delivery/i, "/page/shipping"],
      [/returns & refunds/i, "/page/returns"],
    ];
    for (const [name, href] of expected) {
      expect(screen.getByRole("link", { name })).toHaveAttribute("href", href);
    }
  });

  it("points the links that now have real routes at those routes (2026-08-16)", () => {
    render(<Footer />);
    // Repointed when the header's `More` menu shipped these as code routes. Keeping the
    // footer on `/page/about` would have left two competing URLs for one page — one of
    // them a 404 — and split whatever ranking either earned.
    const moved: [RegExp, string][] = [
      [/^about$/i, "/about-us"],
      [/^blog$/i, "/blog"],
      [/^affiliates$/i, "/affiliates"],
      [/contact us/i, "/contact-us"],
    ];
    for (const [name, href] of moved) {
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
