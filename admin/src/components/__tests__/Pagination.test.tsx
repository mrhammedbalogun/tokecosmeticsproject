import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Pagination } from "@/components/Pagination";
import { auditQueryString } from "@/lib/audit";
import { productsQueryString } from "@/lib/products";

// The component no longer knows about any particular filter shape — the caller supplies a
// query builder (Plan-17a Task 2, when the products list became the second consumer). The
// audit builder is used here so these cases keep asserting the behaviour they always did.
const audit = (filters: Parameters<typeof auditQueryString>[0]) => ({
  page: filters.page,
  buildQuery: (target: number) => auditQueryString({ ...filters, page: target }),
});

describe("Pagination", () => {
  it("carries the active filters onto every page link", () => {
    // THE BUG THIS EXISTS TO PREVENT. Paging with a filter applied must not silently
    // drop it — an operator who filtered to one actor, clicked page 2 and got the
    // unfiltered log would have no way to tell, because page 2 of a filtered log and
    // page 2 of the whole log look identical.
    render(
      <Pagination
        basePath="/settings/audit"
        {...audit({ actor: "owner@toke.test", page: 1 })}
        total={3}
      />,
    );

    const page2 = screen.getByRole("link", { name: "Page 2" });
    expect(page2).toHaveAttribute("href", "/settings/audit?actor=owner%40toke.test&page=2");
  });

  it("renders nothing at all when everything fits on one page", () => {
    const { container } = render(
      <Pagination basePath="/settings/audit" {...audit({ page: 1 })} total={1} />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("marks the current page for assistive technology and does not link it", () => {
    render(<Pagination basePath="/settings/audit" {...audit({ page: 2 })} total={4} />);

    expect(screen.getByText("2")).toHaveAttribute("aria-current", "page");
    expect(screen.queryByRole("link", { name: "Page 2" })).not.toBeInTheDocument();
  });

  it("links page 1 without a page parameter", () => {
    render(<Pagination basePath="/settings/audit" {...audit({ page: 3 })} total={5} />);

    expect(screen.getByRole("link", { name: "Page 1" })).toHaveAttribute(
      "href",
      "/settings/audit",
    );
  });

  it("serves a second list with a different filter vocabulary", () => {
    // The whole point of the generalisation: the products list pages with `search` and
    // `status`, which the audit query builder would have silently dropped.
    const filters = { search: "shea", status: "draft" as const, page: 1 };
    render(
      <Pagination
        basePath="/products"
        page={filters.page}
        total={3}
        buildQuery={(target) => productsQueryString({ ...filters, page: target })}
      />,
    );

    expect(screen.getByRole("link", { name: "Page 2" })).toHaveAttribute(
      "href",
      "/products?search=shea&status=draft&page=2",
    );
  });

  it("names the landmark, so two paged lists are distinguishable", () => {
    render(
      <Pagination
        basePath="/products"
        page={1}
        total={3}
        buildQuery={() => ""}
        label="Product pages"
      />,
    );

    expect(screen.getByRole("navigation", { name: "Product pages" })).toBeInTheDocument();
  });
});
