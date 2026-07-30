import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ProductTable } from "@/components/ProductTable";
import type { ProductRow } from "@/lib/products";

const CURRENCIES = ["NGN", "GBP", "USD", "CAD"];

const row = (overrides: Partial<ProductRow> = {}): ProductRow => ({
  id: 1,
  name: "Carrot Shea Butter",
  slug: "carrot-shea-butter",
  status: "active",
  is_featured: false,
  updated_at: "2026-07-30T10:00:00Z",
  thumbnail: null,
  variant_count: 1,
  priced_currencies: ["NGN"],
  ...overrides,
});

describe("ProductTable", () => {
  it("links each product to its editor by slug", () => {
    render(<ProductTable rows={[row()]} currencies={CURRENCIES} />);

    expect(screen.getByRole("link", { name: "Carrot Shea Butter" })).toHaveAttribute(
      "href",
      "/products/carrot-shea-butter",
    );
  });

  it("says which markets a product is not priced for", () => {
    render(<ProductTable rows={[row({ priced_currencies: ["NGN"] })]} currencies={CURRENCIES} />);

    expect(screen.getByText("GBP, USD, CAD")).toBeInTheDocument();
  });

  it("shows a placeholder rather than an empty cell when there is no image", () => {
    // "This product has no image" is a fact worth seeing on a catalogue where every
    // product is supposed to have one. An empty cell reads as a layout bug.
    render(<ProductTable rows={[row({ thumbnail: null })]} currencies={CURRENCIES} />);

    expect(screen.getByLabelText("No image")).toBeInTheDocument();
  });

  it("renders the thumbnail when there is one", () => {
    render(
      <ProductTable
        rows={[row({ thumbnail: "https://cdn.example.test/catalog/a.png" })]}
        currencies={CURRENCIES}
      />,
    );

    // `alt=""` — decorative, because the product name is right beside it and a screen
    // reader announcing both would read the name twice.
    const img = document.querySelector("img");
    expect(img).toHaveAttribute("src", "https://cdn.example.test/catalog/a.png");
    expect(img).toHaveAttribute("alt", "");
  });

  it("renders the date without applying the server's locale", () => {
    // The server renders this. `toLocaleDateString` would present the SERVER's locale as
    // if it were the reader's, which is how a 03/04 date becomes ambiguous.
    render(<ProductTable rows={[row({ updated_at: "2026-07-30T10:00:00Z" })]} currencies={CURRENCIES} />);

    expect(screen.getByText("2026-07-30")).toBeInTheDocument();
  });

  it("marks a featured product", () => {
    render(<ProductTable rows={[row({ is_featured: true })]} currencies={CURRENCIES} />);

    expect(screen.getByText("Featured")).toBeInTheDocument();
  });

  it("shows the variant count, including for a multi-variant product", () => {
    render(<ProductTable rows={[row({ variant_count: 4 })]} currencies={CURRENCIES} />);

    expect(screen.getByText("4")).toBeInTheDocument();
  });

  it("says so when nothing matched, rather than rendering an empty table", () => {
    render(<ProductTable rows={[]} currencies={CURRENCIES} />);

    expect(screen.getByText("No products match those filters.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});
