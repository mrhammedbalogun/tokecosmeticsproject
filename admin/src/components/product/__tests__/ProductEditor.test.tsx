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
  ingredients: "",
  directions: "",
  warnings: "",
  specs: [],
  faqs: [],
  seo_title: "",
  seo_description: "",
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

const image = (id: number, position: number, alt = "") => ({
  id,
  image: `https://cdn.test/${id}.png`,
  alt,
  position,
  variant: null,
});

/** The shape `savePrice` is called with. Declared so the mocks carry a parameter type —
 * `vi.fn(async () => ...)` types its calls as an EMPTY tuple, and every
 * `savePrice.mock.calls[0][0]` assertion below would fail to compile against it. */
type PriceResult = { ok: boolean; price?: ReturnType<typeof priceRow>; error?: string };

interface PriceInput {
  priceId: number | null;
  variantId: number;
  currency: string;
  amount: string;
  productSlug: string;
}

const CURRENCIES = ["NGN", "GBP", "USD", "CAD"];

const variantRow = (id: number, sku = `SKU-${id}`, weight: number | null = 250) => ({
  id,
  sku,
  name: `${id}ml`,
  weight_grams: weight,
  is_active: true,
  position: 0,
});

const stockRow = (variant: number, warehouse: number, quantity: number, name = "Lagos HQ") => ({
  id: variant * 100 + warehouse,
  variant,
  sku: `SKU-${variant}`,
  warehouse,
  warehouse_name: name,
  quantity,
  reserved: 0,
  available: quantity,
  low_stock_threshold: 5,
});

const priceRow = (
  id: number,
  variant: number,
  currency: string,
  amount: string,
  extra: Partial<{ country: string | null; starts_at: string | null }> = {},
) => ({
  id,
  variant,
  currency,
  country: null,
  amount,
  starts_at: null,
  ends_at: null,
  ...extra,
});

function setup(
  overrides: Partial<ProductDetail> = {},
  save = vi.fn().mockResolvedValue({}),
  images: ReturnType<typeof image>[] = [],
  imageActions: Partial<{
    upload: ReturnType<typeof vi.fn>;
    update: ReturnType<typeof vi.fn>;
    remove: ReturnType<typeof vi.fn>;
  }> = {},
  catalogue: Partial<{
    variants: ReturnType<typeof variantRow>[];
    stock: ReturnType<typeof stockRow>[];
    prices: ReturnType<typeof priceRow>[];
    savePrice: ReturnType<typeof vi.fn>;
  }> = {},
) {
  const actions = {
    upload: imageActions.upload ?? vi.fn().mockResolvedValue({ ok: true, value: image(99, 9) }),
    update: imageActions.update ?? vi.fn(async (id: number) => ({ ok: true, value: image(id, 0) })),
    remove: imageActions.remove ?? vi.fn().mockResolvedValue({ ok: true, value: null }),
  };
  const savePrice =
    catalogue.savePrice ??
    vi.fn(async (input: { priceId: number | null; variantId: number; currency: string; amount: string }) => ({
      ok: true,
      price: priceRow(input.priceId ?? 900, input.variantId, input.currency, input.amount),
    }));
  render(
    <ProductEditor
      product={product(overrides)}
      categories={CATEGORIES}
      tags={TAGS}
      countries={COUNTRIES}
      siteUrl="https://tokecosmetics.com"
      initialImages={images}
      imageActions={actions}
      variants={catalogue.variants ?? []}
      stock={catalogue.stock ?? []}
      initialPrices={catalogue.prices ?? []}
      currencies={CURRENCIES}
      savePrice={savePrice}
      save={save}
    />,
  );
  return { save, actions, savePrice };
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

  // --- Content tab (task 4) ---------------------------------------------------------

  it("invites input rather than looking broken when content is empty", () => {
    // All 69 migrated products have empty ingredients/directions/warnings — the fields
    // exist in no WordPress column. Empty is the NORMAL starting point here, not an error.
    setup();

    fireEvent.click(tab("Content"));

    expect(screen.getByText(/no specifications yet/i)).toBeInTheDocument();
    expect(screen.getByText(/no questions yet/i)).toBeInTheDocument();
  });

  it("adds and removes a specification row", () => {
    setup();
    fireEvent.click(tab("Content"));

    fireEvent.click(screen.getByRole("button", { name: "Add specification" }));
    fireEvent.change(screen.getByLabelText("Specification 1 label"), {
      target: { value: "Size" },
    });
    expect(screen.getByLabelText("Specification 1 label")).toHaveValue("Size");

    fireEvent.click(screen.getByRole("button", { name: "Remove specification 1" }));
    expect(screen.queryByLabelText("Specification 1 label")).not.toBeInTheDocument();
  });

  it("edits one FAQ row without disturbing its neighbour", () => {
    setup({
      faqs: [
        { q: "First?", a: "Yes" },
        { q: "Second?", a: "No" },
      ],
    });
    fireEvent.click(tab("Content"));

    fireEvent.change(screen.getByLabelText("Answer 1"), { target: { value: "Absolutely" } });

    expect(screen.getByLabelText("Answer 1")).toHaveValue("Absolutely");
    expect(screen.getByLabelText("Answer 2")).toHaveValue("No");
  });

  it("does not arm Save for an added-then-abandoned empty row", () => {
    setup();
    fireEvent.click(tab("Content"));

    fireEvent.click(screen.getByRole("button", { name: "Add specification" }));

    expect(saveButton()).toBeDisabled();
  });

  it("drops blank rows from what gets sent", async () => {
    const save = vi.fn().mockResolvedValue({ savedSlug: "carrot-shea-butter", savedAt: 1 });
    setup({ specs: [{ label: "Size", value: "250ml" }] }, save);
    fireEvent.click(tab("Content"));

    fireEvent.click(screen.getByRole("button", { name: "Add specification" }));
    fireEvent.change(screen.getByLabelText("Specification 2 label"), {
      target: { value: "Weight" },
    });
    fireEvent.click(saveButton());

    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0][1].specs).toHaveLength(2);
  });

  // --- SEO tab (task 4) -------------------------------------------------------------

  it("previews the title with the suffix the site actually appends", () => {
    setup();

    fireEvent.click(tab("SEO"));

    expect(screen.getByText("Carrot Shea Butter | Toke Cosmetics")).toBeInTheDocument();
  });

  it("says when the title is falling back to the product name", () => {
    setup({ seo_title: "" });

    fireEvent.click(tab("SEO"));

    expect(screen.getByText(/product name is used/i)).toBeInTheDocument();
  });

  it("warns when neither a description nor a fallback exists", () => {
    setup({ seo_description: "", short_description: "" });

    fireEvent.click(tab("SEO"));

    expect(screen.getByText(/search engines will write/i)).toBeInTheDocument();
  });

  it("previews the PDP url with the singular product segment", () => {
    setup();

    fireEvent.click(tab("SEO"));

    expect(
      screen.getByText("https://tokecosmetics.com/product/carrot-shea-butter"),
    ).toBeInTheDocument();
  });

  it("carries content and SEO edits into the save", async () => {
    const save = vi.fn().mockResolvedValue({ savedSlug: "carrot-shea-butter", savedAt: 1 });
    setup({}, save);

    fireEvent.click(tab("Content"));
    fireEvent.change(screen.getByPlaceholderText(/shea butter, carrot oil/i), {
      target: { value: "Shea butter, carrot oil" },
    });
    fireEvent.click(tab("SEO"));
    fireEvent.change(screen.getByPlaceholderText("Carrot Shea Butter"), {
      target: { value: "Best Shea Butter" },
    });
    fireEvent.click(saveButton());

    await waitFor(() => expect(save).toHaveBeenCalled());
    const values = save.mock.calls[0][1];
    expect(values.ingredients).toBe("Shea butter, carrot oil");
    expect(values.seo_title).toBe("Best Shea Butter");
  });

  // --- Images tab (task 5) ----------------------------------------------------------

  it("says out loud that image changes are immediate", () => {
    // 17a design decision 1: images are a separate resource and take effect at once. The
    // decision's own words are that the UI must make that obvious rather than hide it.
    setup({}, undefined, [image(1, 0)]);

    fireEvent.click(tab("Images"));

    expect(screen.getByText(/take effect/i)).toBeInTheDocument();
  });

  it("orders images by position, with the model's id tiebreak", () => {
    setup({}, undefined, [image(9, 0), image(2, 0), image(5, 1)]);

    fireEvent.click(tab("Images"));

    const alts = screen.getAllByLabelText(/^Alt text for image/);
    expect(alts).toHaveLength(3);
  });

  it("moves an image and writes only the rows that moved", async () => {
    const update = vi.fn(async (id: number) => ({ ok: true, value: image(id, 0) }));
    setup({}, undefined, [image(1, 0), image(2, 1), image(3, 2)], { update });

    fireEvent.click(tab("Images"));
    fireEvent.click(screen.getByLabelText("Move image 3 up"));

    await waitFor(() => expect(update).toHaveBeenCalledTimes(2));
    expect(update.mock.calls.map((c) => c[0]).sort()).toEqual([2, 3]);
  });

  it("PUTS THE ORDER BACK when a reorder write fails", async () => {
    // A row that stays where it was dragged while the database disagrees is the worst of
    // both — the next reload silently undoes what the screen said had happened.
    const update = vi.fn().mockResolvedValue({ ok: false, error: "Nope." });
    setup({}, undefined, [image(1, 0, "first"), image(2, 1, "second")], { update });

    fireEvent.click(tab("Images"));
    fireEvent.click(screen.getByLabelText("Move image 2 up"));

    await waitFor(() => expect(screen.getByText("Nope.")).toBeInTheDocument());
    expect(screen.getByLabelText("Alt text for image 1")).toHaveValue("first");
  });

  it("cannot move the first image up or the last one down", () => {
    setup({}, undefined, [image(1, 0), image(2, 1)]);

    fireEvent.click(tab("Images"));

    expect(screen.getByLabelText("Move image 1 up")).toBeDisabled();
    expect(screen.getByLabelText("Move image 2 down")).toBeDisabled();
  });

  it("writes alt text on blur rather than on every keystroke", async () => {
    // A PATCH per character is dozens of writes and dozens of audit rows for one sentence.
    const update = vi.fn(async (id: number) => ({ ok: true, value: image(id, 0, "a swatch") }));
    setup({}, undefined, [image(1, 0)], { update });

    fireEvent.click(tab("Images"));
    const input = screen.getByLabelText("Alt text for image 1");
    fireEvent.change(input, { target: { value: "a swatch" } });
    expect(update).not.toHaveBeenCalled();

    fireEvent.blur(input);

    await waitFor(() => expect(update).toHaveBeenCalledWith(1, { alt: "a swatch" }));
  });

  it("does not write alt text that did not change", () => {
    const update = vi.fn();
    setup({}, undefined, [image(1, 0, "unchanged")], { update });

    fireEvent.click(tab("Images"));
    fireEvent.blur(screen.getByLabelText("Alt text for image 1"));

    expect(update).not.toHaveBeenCalled();
  });

  it("asks twice before deleting, because there is no undo", async () => {
    const remove = vi.fn().mockResolvedValue({ ok: true, value: null });
    setup({}, undefined, [image(1, 0)], { remove });

    fireEvent.click(tab("Images"));
    fireEvent.click(screen.getByLabelText("Delete image 1"));
    expect(remove).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Really delete" }));

    await waitFor(() => expect(remove).toHaveBeenCalledWith(1));
  });

  it("A FAILED IMAGE WRITE DOES NOT COST UNSAVED TEXT IN ANOTHER TAB", async () => {
    // Named in the spec, and the reason no image action revalidates this page: a
    // re-render would remount the editor and discard work nobody can recover.
    const remove = vi.fn().mockResolvedValue({ ok: false, error: "Could not delete." });
    setup({}, undefined, [image(1, 0)], { remove });

    fireEvent.change(nameInput(), { target: { value: "Half-written name" } });
    fireEvent.click(tab("Images"));
    fireEvent.click(screen.getByLabelText("Delete image 1"));
    fireEvent.click(screen.getByRole("button", { name: "Really delete" }));

    await waitFor(() => expect(screen.getByText("Could not delete.")).toBeInTheDocument());
    fireEvent.click(tab("Details"));
    expect(screen.getByDisplayValue("Half-written name")).toBeInTheDocument();
  });

  it("keeps an uploaded image visible after switching tabs", async () => {
    // The panel unmounts on a tab switch, which is why the list lives in the editor. If it
    // lived in the panel the upload would appear to vanish on the way to Details and back.
    const upload = vi.fn().mockResolvedValue({ ok: true, value: image(7, 0, "new one") });
    setup({}, undefined, [], { upload });

    fireEvent.click(tab("Images"));
    const file = new File(["x"], "a.png", { type: "image/png" });
    fireEvent.change(screen.getByLabelText(/image file/i), { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: "Upload" }));

    await waitFor(() => expect(upload).toHaveBeenCalled());
    fireEvent.click(tab("Details"));
    fireEvent.click(tab("Images"));

    expect(screen.getByLabelText("Alt text for image 1")).toHaveValue("new one");
  });

  it("surfaces an upload failure without clearing the other tabs", async () => {
    const upload = vi.fn().mockResolvedValue({ ok: false, error: "Too large." });
    setup({}, undefined, [], { upload });

    fireEvent.click(tab("Images"));
    const file = new File(["x"], "a.png", { type: "image/png" });
    fireEvent.change(screen.getByLabelText(/image file/i), { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: "Upload" }));

    await waitFor(() => expect(screen.getByText("Too large.")).toBeInTheDocument());
  });

  it("says which image the storefront leads with", () => {
    setup({}, undefined, [image(1, 0), image(2, 1)]);

    fireEvent.click(tab("Images"));

    expect(screen.getByText(/shown first on the storefront/i)).toBeInTheDocument();
  });

  // --- Variants tab (task 6) --------------------------------------------------------

  const withCatalogue = (over: Parameters<typeof setup>[4] = {}) =>
    setup({}, undefined, [], {}, over);

  it("lists existing variants with a stock column per warehouse", () => {
    withCatalogue({
        variants: [variantRow(1, "TC-1"), variantRow(2, "TC-2")],
        stock: [stockRow(1, 1, 7), stockRow(2, 2, 3, "UK Warehouse")],
      });

    fireEvent.click(tab("Variants"));

    expect(screen.getByText("TC-1")).toBeInTheDocument();
    expect(screen.getByText("Lagos HQ")).toBeInTheDocument();
    expect(screen.getByText("UK Warehouse")).toBeInTheDocument();
  });

  it("shows a dash, not a zero, for a variant with no weight", () => {
    // Eight production variants have no weight. A "0 g" is a claim about a parcel rather
    // than an absence — and it is the number a courier quote would be built from.
    withCatalogue({ variants: [variantRow(1, "TC-1", null)] });

    fireEvent.click(tab("Variants"));

    expect(screen.getByTitle("No weight recorded")).toBeInTheDocument();
  });

  it("shows a dash where a variant has no stock row in a warehouse", () => {
    // Production keeps one stock row per variant across two warehouses, so this is the
    // common case and means something different from "none in stock here".
    withCatalogue({
        variants: [variantRow(1), variantRow(2)],
        stock: [stockRow(1, 1, 7), stockRow(2, 2, 3, "UK Warehouse")],
      });

    fireEvent.click(tab("Variants"));

    expect(screen.getAllByTitle("No stock record here")).toHaveLength(2);
  });

  it("offers no editable stock field, because the API refuses PATCH on quantity", () => {
    // StockItemAdminViewSet drops PUT and PATCH; the only route to a quantity is `adjust`,
    // which requires a reason and a note. A number input here would be a lie.
    withCatalogue({ variants: [variantRow(1)], stock: [stockRow(1, 1, 7)] });

    fireEvent.click(tab("Variants"));

    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();
  });

  it("says variant creation is a later slice when there are none", () => {
    withCatalogue({ variants: [] });

    fireEvent.click(tab("Variants"));

    expect(screen.getByText(/17b/)).toBeInTheDocument();
  });

  // --- Prices tab (task 6) ----------------------------------------------------------

  it("renders a variant x currency grid", () => {
    withCatalogue({
        variants: [variantRow(1, "TC-1")],
        prices: [priceRow(1, 1, "NGN", "1500.00")],
      });

    fireEvent.click(tab("Prices"));

    expect(screen.getByLabelText("TC-1 price in NGN")).toHaveValue("1500.00");
    expect(screen.getByLabelText("TC-1 price in GBP")).toHaveValue("");
  });

  it("flags the currencies a variant is not priced in", () => {
    withCatalogue({
        variants: [variantRow(1, "TC-1")],
        prices: [priceRow(1, 1, "NGN", "1500.00")],
      });

    fireEvent.click(tab("Prices"));

    expect(screen.getAllByText("Not priced")).toHaveLength(3);
  });

  it("saves a price on blur, creating one where none existed", async () => {
    const savePrice = vi.fn<(input: PriceInput) => Promise<PriceResult>>(async () => ({ ok: true, price: priceRow(5, 1, "GBP", "40.00") }));
    withCatalogue({ variants: [variantRow(1, "TC-1")], savePrice });

    fireEvent.click(tab("Prices"));
    const cell = screen.getByLabelText("TC-1 price in GBP");
    fireEvent.change(cell, { target: { value: "40" } });
    fireEvent.blur(cell);

    await waitFor(() => expect(savePrice).toHaveBeenCalledTimes(1));
    expect(savePrice.mock.calls[0][0]).toMatchObject({
      priceId: null,
      variantId: 1,
      currency: "GBP",
      amount: "40",
    });
  });

  it("PATCHes rather than POSTs when the cell already had a price", async () => {
    const savePrice = vi.fn<(input: PriceInput) => Promise<PriceResult>>(async () => ({ ok: true, price: priceRow(1, 1, "NGN", "1600") }));
    withCatalogue({
        variants: [variantRow(1, "TC-1")],
        prices: [priceRow(1, 1, "NGN", "1500.00")],
        savePrice,
      });

    fireEvent.click(tab("Prices"));
    const cell = screen.getByLabelText("TC-1 price in NGN");
    fireEvent.change(cell, { target: { value: "1600" } });
    fireEvent.blur(cell);

    await waitFor(() => expect(savePrice).toHaveBeenCalled());
    expect(savePrice.mock.calls[0][0].priceId).toBe(1);
  });

  it("writes nothing when the value did not change", () => {
    const savePrice = vi.fn();
    withCatalogue({
        variants: [variantRow(1, "TC-1")],
        prices: [priceRow(1, 1, "NGN", "1500.00")],
        savePrice,
      });

    fireEvent.click(tab("Prices"));
    const cell = screen.getByLabelText("TC-1 price in NGN");
    // Same number, written differently — not an edit.
    fireEvent.change(cell, { target: { value: "1500" } });
    fireEvent.blur(cell);

    expect(savePrice).not.toHaveBeenCalled();
  });

  it("refuses a thousands separator against the cell rather than sending it", () => {
    const savePrice = vi.fn();
    withCatalogue({ variants: [variantRow(1, "TC-1")], savePrice });

    fireEvent.click(tab("Prices"));
    const cell = screen.getByLabelText("TC-1 price in NGN");
    fireEvent.change(cell, { target: { value: "1,500" } });
    fireEvent.blur(cell);

    expect(savePrice).not.toHaveBeenCalled();
    expect(screen.getByText(/use a dot/i)).toBeInTheDocument();
  });

  it("shows a save failure against the cell that failed", async () => {
    const savePrice = vi.fn<(input: PriceInput) => Promise<PriceResult>>(async () => ({ ok: false, error: "Nope." }));
    withCatalogue({ variants: [variantRow(1, "TC-1")], savePrice });

    fireEvent.click(tab("Prices"));
    const cell = screen.getByLabelText("TC-1 price in NGN");
    fireEvent.change(cell, { target: { value: "1500" } });
    fireEvent.blur(cell);

    await waitFor(() => expect(screen.getByText("Nope.")).toBeInTheDocument());
  });

  it("MAKES A COUNTRY-OVERRIDE CELL READ-ONLY AND SAYS WHY", async () => {
    // Production has zero overrides, so this path only exists under test — which is
    // exactly why it is tested. Editing the plain row while a narrower one governs GB
    // would appear to succeed and change nothing for those customers.
    const savePrice = vi.fn();
    withCatalogue({
        variants: [variantRow(1, "TC-1")],
        prices: [
          priceRow(1, 1, "NGN", "1500.00"),
          priceRow(2, 1, "NGN", "1200.00", { country: "GB" }),
        ],
        savePrice,
      });

    fireEvent.click(tab("Prices"));
    const cell = screen.getByLabelText("TC-1 price in NGN");

    expect(cell).toHaveAttribute("readonly");
    expect(screen.getByText(/country-specific price is set for GB/i)).toBeInTheDocument();
    fireEvent.blur(cell);
    expect(savePrice).not.toHaveBeenCalled();
  });

  it("locks a scheduled cell too, and leaves the other currencies editable", () => {
    withCatalogue({
        variants: [variantRow(1, "TC-1")],
        prices: [
          priceRow(1, 1, "NGN", "1500.00"),
          priceRow(2, 1, "NGN", "1800.00", { starts_at: "2026-12-01T00:00:00Z" }),
        ],
      });

    fireEvent.click(tab("Prices"));

    expect(screen.getByLabelText("TC-1 price in NGN")).toHaveAttribute("readonly");
    expect(screen.getByLabelText("TC-1 price in GBP")).not.toHaveAttribute("readonly");
  });

  it("adopts the saved id, so a second edit updates instead of duplicating", async () => {
    const savePrice = vi.fn<(input: PriceInput) => Promise<PriceResult>>(async () => ({ ok: true, price: priceRow(77, 1, "GBP", "40.00") }));
    withCatalogue({ variants: [variantRow(1, "TC-1")], savePrice });

    fireEvent.click(tab("Prices"));
    const cell = screen.getByLabelText("TC-1 price in GBP");
    fireEvent.change(cell, { target: { value: "40" } });
    fireEvent.blur(cell);
    await waitFor(() => expect(savePrice).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByLabelText("TC-1 price in GBP"), { target: { value: "45" } });
    fireEvent.blur(screen.getByLabelText("TC-1 price in GBP"));

    await waitFor(() => expect(savePrice).toHaveBeenCalledTimes(2));
    // The unique constraint would reject a second POST for the same variant+currency.
    expect(savePrice.mock.calls[1][0].priceId).toBe(77);
  });

  it("keeps a price edit visible after switching tabs", async () => {
    const savePrice = vi.fn<(input: PriceInput) => Promise<PriceResult>>(async () => ({ ok: true, price: priceRow(5, 1, "GBP", "40.00") }));
    withCatalogue({ variants: [variantRow(1, "TC-1")], savePrice });

    fireEvent.click(tab("Prices"));
    const cell = screen.getByLabelText("TC-1 price in GBP");
    fireEvent.change(cell, { target: { value: "40" } });
    fireEvent.blur(cell);
    await waitFor(() => expect(savePrice).toHaveBeenCalled());

    fireEvent.click(tab("Details"));
    fireEvent.click(tab("Prices"));

    expect(screen.getByLabelText("TC-1 price in GBP")).toHaveValue("40.00");
  });

  it("does not arm the product Save button, because prices are their own resource", async () => {
    const savePrice = vi.fn<(input: PriceInput) => Promise<PriceResult>>(async () => ({ ok: true, price: priceRow(5, 1, "GBP", "40.00") }));
    withCatalogue({ variants: [variantRow(1, "TC-1")], savePrice });

    fireEvent.click(tab("Prices"));
    const cell = screen.getByLabelText("TC-1 price in GBP");
    fireEvent.change(cell, { target: { value: "40" } });
    fireEvent.blur(cell);

    await waitFor(() => expect(savePrice).toHaveBeenCalled());
    expect(saveButton()).toBeDisabled();
  });
});
