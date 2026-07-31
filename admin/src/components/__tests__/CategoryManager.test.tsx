import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { CategoryManager } from "@/components/CategoryManager";
import { orderCategories, type CategoryRef } from "@/lib/category-tree";
import type { CategoryState } from "@/app/(shell)/categories/actions";

const cat = (
  id: number,
  parent: number | null,
  name: string,
  extra: Partial<CategoryRef> = {},
): CategoryRef => ({
  id,
  name,
  slug: name.toLowerCase().replace(/\s+/g, "-"),
  parent,
  is_active: true,
  sort_order: 0,
  ...extra,
});

/*  Skincare ─ Cleansers ─ Foaming
    Haircare  */
const TREE = orderCategories([
  cat(1, null, "Skincare"),
  cat(2, 1, "Cleansers"),
  cat(3, 2, "Foaming"),
  cat(4, null, "Haircare", { is_active: false }),
]);

function setup(state: CategoryState = {}, counts: Record<number, number> = {}) {
  const action = vi.fn(async () => state);
  const { container } = render(
    <CategoryManager categories={TREE} counts={counts} action={action} />,
  );
  return { action, container };
}

const parentSelect = () => screen.getByLabelText("Parent") as HTMLSelectElement;
const options = () => [...parentSelect().options].map((o) => o.text.replace(/—\s*/g, "").trim());

describe("CategoryManager", () => {
  it("indents the tree by depth", () => {
    setup();

    const foaming = screen.getByRole("button", { name: /Foaming/ });
    expect(foaming).toHaveStyle({ paddingLeft: "52px" }); // 12 + 2 * 20
  });

  it("marks a hidden category rather than omitting it", () => {
    setup();

    const haircare = screen.getByRole("button", { name: /Haircare/ });
    expect(within(haircare).getByText("Hidden")).toBeInTheDocument();
  });

  it("shows the product count, because that answers 'can I hide this?'", () => {
    setup({}, { 1: 7 });

    expect(screen.getByRole("button", { name: /Skincare/ })).toHaveTextContent("7 products");
  });

  it("says 0 products for a category nothing uses", () => {
    setup();

    expect(screen.getByRole("button", { name: /Haircare/ })).toHaveTextContent("0 products");
  });

  it("loads the clicked category into the form", () => {
    setup();

    fireEvent.click(screen.getByRole("button", { name: /Cleansers/ }));

    expect(screen.getByLabelText("Name")).toHaveValue("Cleansers");
  });

  it("REPLACES the form values when a different category is picked", () => {
    // Without re-keying the uncontrolled inputs, the previous category's name stays in
    // the box — an edit form quietly pointed at the wrong record.
    setup();

    fireEvent.click(screen.getByRole("button", { name: /Cleansers/ }));
    fireEvent.click(screen.getByRole("button", { name: /Haircare/ }));

    expect(screen.getByLabelText("Name")).toHaveValue("Haircare");
  });

  it("OMITS THE CATEGORY AND ITS WHOLE SUBTREE from the parent options", () => {
    // Choosing one of those makes a cycle, which hangs the storefront breadcrumb walk
    // and its recursive tree serializer. The backend refuses them too — this just means
    // nobody has to find out by being refused.
    setup();

    fireEvent.click(screen.getByRole("button", { name: /Skincare/ }));

    expect(options()).not.toContain("Skincare");
    expect(options()).not.toContain("Cleansers");
    expect(options()).not.toContain("Foaming");
    expect(options()).toContain("Haircare");
  });

  it("always offers a top-level option", () => {
    setup();

    expect(options()).toContain("No parent (top level)");
  });

  it("preselects the current parent", () => {
    setup();

    fireEvent.click(screen.getByRole("button", { name: /Cleansers/ }));

    expect(parentSelect().value).toBe("1");
  });

  it("selects the empty option for a root category", () => {
    setup();

    fireEvent.click(screen.getByRole("button", { name: /Haircare/ }));

    expect(parentSelect().value).toBe("");
  });

  it("carries the identifying slug in a hidden field", () => {
    // The PATCH addresses the category by its CURRENT slug, which the form may be about
    // to change.
    const { container } = setup();

    fireEvent.click(screen.getByRole("button", { name: /Cleansers/ }));

    expect(container.querySelector('input[name="current_slug"]')).toHaveValue("cleansers");
  });

  it("shows a field error against its input", async () => {
    const { container } = setup({
      fieldErrors: { parent: "“Cleansers” is inside “Skincare”, so it cannot also be its parent." },
    });

    fireEvent.submit(container.querySelector("form")!);

    await waitFor(() =>
      expect(screen.getByText(/cannot also be its parent/)).toBeInTheDocument(),
    );
  });

  it("confirms a save", async () => {
    const { container } = setup({ saved: "Skincare" });

    fireEvent.submit(container.querySelector("form")!);

    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Saved Skincare."));
  });

  it("says so when there are no categories at all", () => {
    render(<CategoryManager categories={[]} counts={{}} action={vi.fn(async () => ({}))} />);

    expect(screen.getByText("No categories yet.")).toBeInTheDocument();
  });
});
