import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Pagination } from "@/components/Pagination";

describe("Pagination", () => {
  it("carries the active filters onto every page link", () => {
    // THE BUG THIS EXISTS TO PREVENT. Paging with a filter applied must not silently
    // drop it — an operator who filtered to one actor, clicked page 2 and got the
    // unfiltered log would have no way to tell, because page 2 of a filtered log and
    // page 2 of the whole log look identical.
    render(
      <Pagination basePath="/settings/audit" filters={{ actor: "owner@toke.test", page: 1 }} total={3} />,
    );

    const page2 = screen.getByRole("link", { name: "Page 2" });
    expect(page2).toHaveAttribute("href", "/settings/audit?actor=owner%40toke.test&page=2");
  });

  it("renders nothing at all when everything fits on one page", () => {
    const { container } = render(
      <Pagination basePath="/settings/audit" filters={{ page: 1 }} total={1} />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("marks the current page for assistive technology and does not link it", () => {
    render(<Pagination basePath="/settings/audit" filters={{ page: 2 }} total={4} />);

    expect(screen.getByText("2")).toHaveAttribute("aria-current", "page");
    expect(screen.queryByRole("link", { name: "Page 2" })).not.toBeInTheDocument();
  });

  it("links page 1 without a page parameter", () => {
    render(<Pagination basePath="/settings/audit" filters={{ page: 3 }} total={5} />);

    expect(screen.getByRole("link", { name: "Page 1" })).toHaveAttribute(
      "href",
      "/settings/audit",
    );
  });
});
