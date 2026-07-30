import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ProductEditor } from "@/components/product/ProductEditor";
import type { ProductDetail } from "@/lib/product-form";
import type { CategoryRef, CountryRef, TagRef } from "@/lib/reference";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));

const product = (overrides: Partial<ProductDetail> = {}): ProductDetail => ({
  id: 1,
  name: "Carrot Shea Butter",
  slug: "carrot-shea-butter",
  status: "active",
  short_description: "",
  description: "",
  is_featured: false,
  categories: [],
  tags: [],
  available_countries: [],
  updated_at: "2026-07-30T10:00:00Z",
  variant_count: 1,
  thumbnail: null,
  priced_currencies: ["NGN"],
  ...overrides,
});

const CATEGORIES: CategoryRef[] = [
  { id: 1, name: "Skincare", slug: "skincare", parent: null, is_active: true, sort_order: 0 },
  { id: 2, name: "Cleansers", slug: "cleansers", parent: 1, is_active: true, sort_order: 0 },
];
const TAGS: TagRef[] = [{ id: 5, name: "bestseller", slug: "bestseller" }];
const COUNTRIES: CountryRef[] = [
  { code: "NG", name: "Nigeria", is_rest_of_world: false },
  { code: "GB", name: "United Kingdom", is_rest_of_world: false },
  { code: "ZZ", name: "International", is_rest_of_world: true },
];

function setup(overrides: Partial<ProductDetail> = {}, save = vi.fn().mockResolvedValue({})) {
  render(
    <ProductEditor
      product={product(overrides)}
      categories={CATEGORIES}
      tags={TAGS}
      countries={COUNTRIES}
      save={save}
    />,
  );
  return { save };
}

const tab = (name: string) => screen.getByRole("tab", { name });
const saveButton = () => screen.getByRole("button", { name: /save/i });
const featured = () => screen.getByRole("checkbox", { name: /featured/i });
const nameInput = () => screen.getByDisplayValue("Carrot Shea Butter");
const slugInput = () => screen.getByDisplayValue("carrot-shea-butter");

beforeEach(() => replace.mockClear());

describe("ProductEditor", () => {
  it("starts clean, with Save disabled", () => {
    setup();

    expect(saveButton()).toBeDisabled();
    expect(screen.queryByText(/unsaved changes/i)).not.toBeInTheDocument();
  });

  it("shows unsaved changes as soon as a field moves", () => {
    setup();

    fireEvent.change(nameInput(), { target: { value: "Carrot Shea Butter Deluxe" } });

    expect(screen.getByText(/unsaved changes/i)).toBeInTheDocument();
    expect(saveButton()).toBeEnabled();
  });

  it("KEEPS UNSAVED EDITS WHEN THE TAB CHANGES", () => {
    // The whole point of 17a design decision 3. URL-driven tabs would make this a
    // navigation, and navigation destroys the form — losing a half-written description
    // because somebody clicked "Availability" is a data-loss bug, not a UX wrinkle.
    setup();

    fireEvent.change(nameInput(), { target: { value: "Carrot Shea Butter Deluxe" } });
    fireEvent.click(tab("Availability"));
    fireEvent.click(tab("Details"));

    expect(screen.getByDisplayValue("Carrot Shea Butter Deluxe")).toBeInTheDocument();
  });

  it("sends every editable field, with the edit applied", async () => {
    const save = vi.fn().mockResolvedValue({ savedSlug: "carrot-shea-butter", savedAt: 1 });
    setup({}, save);

    fireEvent.click(featured());
    fireEvent.click(saveButton());

    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    const [slug, values] = save.mock.calls[0];
    expect(slug).toBe("carrot-shea-butter");
    expect(values.is_featured).toBe(true);
    expect(values.name).toBe("Carrot Shea Butter");
  });

  it("saves against the ORIGINAL slug even after the slug field is edited", async () => {
    // The slug is the URL the record lives at. PATCHing to the NEW slug would address a
    // product that does not exist yet and 404 — the rename has to be sent to the old one.
    const save = vi.fn().mockResolvedValue({ savedSlug: "new-slug", savedAt: 1 });
    setup({}, save);

    fireEvent.change(slugInput(), { target: { value: "new-slug" } });
    fireEvent.click(saveButton());

    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    expect(save.mock.calls[0][0]).toBe("carrot-shea-butter");
    expect(save.mock.calls[0][1].slug).toBe("new-slug");
  });

  it("clears the unsaved bar after a successful save", async () => {
    const save = vi.fn().mockResolvedValue({ savedSlug: "carrot-shea-butter", savedAt: 1 });
    setup({}, save);

    fireEvent.click(featured());
    fireEvent.click(saveButton());

    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Saved."));
    expect(screen.queryByText(/unsaved changes/i)).not.toBeInTheDocument();
  });

  it("follows the slug to its new URL, replacing rather than pushing", async () => {
    // The old slug now 404s. Leaving it in history hands the back button a broken page.
    const save = vi.fn().mockResolvedValue({ savedSlug: "new-slug", savedAt: 1 });
    setup({}, save);

    fireEvent.change(slugInput(), { target: { value: "new-slug" } });
    fireEvent.click(saveButton());

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/products/new-slug"));
  });

  it("does not navigate when the slug did not move", async () => {
    const save = vi.fn().mockResolvedValue({ savedSlug: "carrot-shea-butter", savedAt: 1 });
    setup({}, save);

    fireEvent.click(featured());
    fireEvent.click(saveButton());

    await waitFor(() => expect(screen.getByRole("status")).toBeInTheDocument());
    expect(replace).not.toHaveBeenCalled();
  });

  it("puts a field error against its input and a banner error at the top", async () => {
    const save = vi.fn().mockResolvedValue({
      errors: { fields: { slug: "Already taken." }, banner: "Nothing was saved." },
    });
    setup({}, save);

    fireEvent.click(featured());
    fireEvent.click(saveButton());

    await waitFor(() => expect(screen.getByText("Already taken.")).toBeInTheDocument());
    expect(screen.getByText("Nothing was saved.")).toBeInTheDocument();
  });

  it("drops a stale error as soon as the field is edited again", async () => {
    // Left on screen an old error reads as "still wrong", and people re-fix a field that
    // is already fine.
    const save = vi.fn().mockResolvedValue({ errors: { fields: { slug: "Already taken." } } });
    setup({}, save);

    fireEvent.click(featured());
    fireEvent.click(saveButton());
    await waitFor(() => expect(screen.getByText("Already taken.")).toBeInTheDocument());

    fireEvent.change(slugInput(), { target: { value: "carrot-shea-butter-2" } });

    expect(screen.queryByText("Already taken.")).not.toBeInTheDocument();
  });

  it("says an empty market list means EVERYWHERE, not nowhere", () => {
    // `available_countries` empty = no restriction (catalog/models.py:132-134). A bare
    // checkbox grid renders "none ticked" and "sold everywhere" identically, so somebody
    // clearing the last box to withdraw a product would publish it to every market.
    setup({ available_countries: [] });

    fireEvent.click(tab("Availability"));

    expect(screen.getByText(/sold in every market/i)).toBeInTheDocument();
  });

  it("switches to the restricted wording once a market is ticked", () => {
    setup({ available_countries: [] });

    fireEvent.click(tab("Availability"));
    fireEvent.click(screen.getByRole("checkbox", { name: /Nigeria/ }));

    expect(screen.queryByText(/sold in every market/i)).not.toBeInTheDocument();
    expect(screen.getByText(/markets? only/i)).toBeInTheDocument();
  });

  it("names Rest of World, because ZZ means nothing to a reader", () => {
    setup();

    fireEvent.click(tab("Availability"));

    expect(screen.getByText("(Rest of World)")).toBeInTheDocument();
  });

  it("ticks the markets the product is already restricted to", () => {
    setup({ available_countries: ["GB"] });

    fireEvent.click(tab("Availability"));

    expect(screen.getByRole("checkbox", { name: /United Kingdom/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /Nigeria/ })).not.toBeChecked();
  });

  it("indents a child category under its parent", () => {
    setup();

    const child = screen.getByRole("checkbox", { name: "Cleansers" }).closest("label");
    expect(child).toHaveStyle({ paddingLeft: "16px" });
  });

  it("toggles a category without disturbing the others", () => {
    setup({ categories: [1] });

    fireEvent.click(screen.getByRole("checkbox", { name: "Cleansers" }));

    expect(screen.getByRole("checkbox", { name: "Skincare" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Cleansers" })).toBeChecked();
  });
});
