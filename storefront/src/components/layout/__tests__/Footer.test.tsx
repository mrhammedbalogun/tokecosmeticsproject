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

  it("keeps payment logos and shows the Lagos legal strip", () => {
    render(<Footer />);
    expect(screen.getByText(/© \d{4} Toke Cosmetics · Lagos, Nigeria/)).toBeInTheDocument();
    // `capitalize` is CSS-only — DOM text stays lowercase.
    expect(screen.getByText("visa")).toBeInTheDocument();
    expect(screen.getByText("bank transfer")).toBeInTheDocument();
  });

  it("exposes social profiles with accessible labels", () => {
    render(<Footer />);
    expect(screen.getByRole("link", { name: "Instagram" })).toHaveAttribute(
      "href",
      "https://www.instagram.com/tokecosmetics",
    );
  });
});
