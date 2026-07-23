import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Pagination } from "@/components/plp/Pagination";

describe("Pagination", () => {
  it("renders nothing when the API reports neither prev nor next", () => {
    const { container } = render(
      <Pagination base="/products" state={{ page: 1 }} hasPrev={false} hasNext={false} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("shows only Next on the first page and links to page 2", () => {
    render(<Pagination base="/products" state={{ page: 1 }} hasPrev={false} hasNext />);
    expect(screen.queryByRole("link", { name: /prev/i })).toBeNull();
    const next = screen.getByRole("link", { name: /next/i });
    expect(next).toHaveAttribute("href", "/products?page=2");
    expect(next).toHaveAttribute("rel", "next");
  });

  it("shows only Prev on the last page (no next link to a 404 page)", () => {
    render(<Pagination base="/products" state={{ brand: "x", page: 3 }} hasPrev hasNext={false} />);
    expect(screen.queryByRole("link", { name: /next/i })).toBeNull();
    const prev = screen.getByRole("link", { name: /prev/i });
    expect(prev).toHaveAttribute("href", "/products?brand=x&page=2");
  });
});
