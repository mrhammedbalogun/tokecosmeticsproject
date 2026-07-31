import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NewProductForm } from "@/components/product/NewProductForm";
import type { CreateState } from "@/app/(shell)/products/new/actions";

function setup(state: CreateState = {}) {
  const action = vi.fn(async () => state);
  const { container } = render(<NewProductForm action={action} />);
  return { action, container };
}

/**
 * Submit and wait for the returned state to land.
 *
 * `useActionState` starts from the INITIAL state, so an error only exists after the action
 * has run — rendering with an action that would return one shows nothing. Driving the real
 * submit is both the accurate test and the only one that works.
 */
async function submit(container: HTMLElement) {
  fireEvent.submit(container.querySelector("form")!);
}

const nameField = () => screen.getByPlaceholderText("Carrot Shea Butter");
const slugField = () => screen.getByPlaceholderText("carrot-shea-butter");

describe("NewProductForm", () => {
  it("fills the slug from the name as it is typed", () => {
    setup();

    fireEvent.change(nameField(), { target: { value: "Carrot Shea Butter" } });

    expect(slugField()).toHaveValue("carrot-shea-butter");
  });

  it("STOPS auto-filling once the slug is edited by hand", () => {
    // Silently rewriting a deliberate slug is noticed only after the product is live and
    // the URL is wrong.
    setup();

    fireEvent.change(nameField(), { target: { value: "Carrot Shea" } });
    fireEvent.change(slugField(), { target: { value: "shea-butter-2026" } });
    fireEvent.change(nameField(), { target: { value: "Carrot Shea Butter Deluxe" } });

    expect(slugField()).toHaveValue("shea-butter-2026");
  });

  it("resumes auto-filling if the slug is cleared", () => {
    setup();

    fireEvent.change(nameField(), { target: { value: "Kids" } });
    fireEvent.change(slugField(), { target: { value: "" } });
    fireEvent.change(nameField(), { target: { value: "Kids Shampoo" } });

    expect(slugField()).toHaveValue("kids-shampoo");
  });

  it("previews the storefront URL the slug will produce", () => {
    setup();

    fireEvent.change(nameField(), { target: { value: "Carrot Shea Butter" } });

    // Singular `/product/`, matching the PDP route — `/products` is the listing.
    expect(screen.getByText("/product/carrot-shea-butter")).toBeInTheDocument();
  });

  it("says the product will be created as a draft", () => {
    setup();

    expect(screen.getByText(/created as a/i)).toHaveTextContent(/draft/i);
  });

  it("shows a field error against its input", async () => {
    const { container } = setup({
      fieldErrors: { slug: "product with this slug already exists." },
    });

    await submit(container);

    await waitFor(() =>
      expect(screen.getByText("product with this slug already exists.")).toBeInTheDocument(),
    );
  });

  it("shows a banner error above the form", async () => {
    const { container } = setup({ error: "Your role does not include managing products." });

    await submit(container);

    await waitFor(() =>
      expect(
        screen.getByText("Your role does not include managing products."),
      ).toBeInTheDocument(),
    );
  });

  it("offers a way out that does not submit", () => {
    setup();

    expect(screen.getByRole("link", { name: "Cancel" })).toHaveAttribute("href", "/products");
  });
});
