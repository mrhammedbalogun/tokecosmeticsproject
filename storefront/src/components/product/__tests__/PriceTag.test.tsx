import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PriceTag } from "@/components/product/PriceTag";

describe("PriceTag", () => {
  it("renders the API amount verbatim with symbol + grouping", () => {
    render(<PriceTag amount="18500.00" currency="NGN" />);
    expect(screen.getByText("₦18,500.00")).toBeInTheDocument();
  });
  it("shows compare-at as struck-through with an accessible name", () => {
    render(<PriceTag amount="18500.00" compareAt="23125.00" currency="NGN" />);
    const was = screen.getByText("₦23,125.00");
    expect(was.tagName).toBe("S");
    expect(screen.getByText(/was/i)).toBeInTheDocument(); // sr-only prefix
  });
  it("renders a from-prefix when asked", () => {
    render(<PriceTag amount="9.50" currency="GBP" from />);
    expect(screen.getByText(/from/i)).toBeInTheDocument();
    expect(screen.getByText("£9.50")).toBeInTheDocument();
  });
});
