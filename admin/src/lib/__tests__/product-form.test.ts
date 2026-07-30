import { describe, it, expect } from "vitest";
import {
  EDITABLE_FIELDS,
  isDirty,
  parseFieldErrors,
  toFormValues,
  toPatchPayload,
  type ProductDetail,
  type ProductFormValues,
} from "@/lib/product-form";

const values = (overrides: Partial<ProductFormValues> = {}): ProductFormValues => ({
  name: "Carrot Shea Butter",
  slug: "carrot-shea-butter",
  status: "active",
  short_description: "",
  description: "",
  is_featured: false,
  categories: [1, 2],
  tags: [5],
  available_countries: ["NG"],
  ...overrides,
});

const detail = (overrides: Partial<ProductDetail> = {}): ProductDetail => ({
  ...values(),
  id: 1,
  updated_at: "2026-07-30T10:00:00Z",
  variant_count: 1,
  thumbnail: null,
  priced_currencies: ["NGN"],
  ...overrides,
});

describe("toFormValues", () => {
  it("copies the arrays rather than aliasing them", () => {
    // The client component mutates these. Sharing the reference with the loaded product
    // would make the dirty check answer "no" after every edit, because both sides move.
    const product = detail();
    const form = toFormValues(product);

    form.categories.push(99);

    expect(product.categories).toEqual([1, 2]);
  });

  it("substitutes empty strings for absent prose", () => {
    // DRF sends "" for a blank TextField, but a hand-built fixture or a future partial
    // serializer could omit it, and `undefined` in a controlled input makes React switch
    // the field to uncontrolled mid-edit.
    const product = { ...detail(), description: undefined } as unknown as ProductDetail;

    expect(toFormValues(product).description).toBe("");
  });
});

describe("toPatchPayload", () => {
  it("sends exactly the editable fields and nothing else", () => {
    // "One PATCH" must not become "PATCH everything the serializer accepts". `brand`,
    // `related`, `published_at` and the legacy columns are writable and are owned by no
    // built tab — sending undefined for them would clobber values nobody can see.
    expect(Object.keys(toPatchPayload(values())).sort()).toEqual([...EDITABLE_FIELDS].sort());
  });

  it("includes empty collections rather than omitting them", () => {
    // Omitting an empty array would make "cleared the last category" indistinguishable
    // from "did not touch categories", and PATCH would keep the old value.
    const payload = toPatchPayload(values({ categories: [], available_countries: [] }));

    expect(payload.categories).toEqual([]);
    expect(payload.available_countries).toEqual([]);
  });
});

describe("isDirty", () => {
  it("is false for an untouched form", () => {
    expect(isDirty(values(), values())).toBe(false);
  });

  it("notices a changed scalar", () => {
    expect(isDirty(values(), values({ name: "Something else" }))).toBe(true);
    expect(isDirty(values(), values({ is_featured: true }))).toBe(true);
  });

  it("ignores the order of a multi-select", () => {
    // A checkbox grid produces whatever order the user clicked in. "NG,GB" and "GB,NG"
    // are the same set of markets, and calling that an edit would leave the unsaved-
    // changes bar up forever.
    expect(isDirty(values({ categories: [1, 2] }), values({ categories: [2, 1] }))).toBe(false);
  });

  it("notices an added and a removed member", () => {
    expect(isDirty(values({ categories: [1, 2] }), values({ categories: [1, 2, 3] }))).toBe(true);
    expect(isDirty(values({ categories: [1, 2] }), values({ categories: [1] }))).toBe(true);
  });

  it("notices a cleared collection", () => {
    expect(isDirty(values(), values({ available_countries: [] }))).toBe(true);
  });
});

describe("parseFieldErrors", () => {
  it("maps DRF field errors onto their inputs", () => {
    const errors = parseFieldErrors({ slug: ["product with this slug already exists."] });

    expect(errors.fields.slug).toBe("product with this slug already exists.");
    expect(errors.banner).toBeUndefined();
  });

  it("puts a `detail` refusal in the banner", () => {
    const errors = parseFieldErrors({ detail: "You do not have permission." });

    expect(errors.banner).toBe("You do not have permission.");
    expect(errors.fields).toEqual({});
  });

  it("puts non_field_errors in the banner", () => {
    const errors = parseFieldErrors({ non_field_errors: ["That combination is taken."] });

    expect(errors.banner).toBe("That combination is taken.");
  });

  it("does not swallow an error for a field no built tab renders", () => {
    // `published_at` belongs to no panel yet. Dropping its message would fail the save
    // with a blank form and no explanation anywhere on screen.
    const errors = parseFieldErrors({ published_at: ["Enter a valid date/time."] });

    expect(errors.banner).toContain("Enter a valid date/time.");
  });

  it("survives a body that is not an object", () => {
    expect(parseFieldErrors(null).fields).toEqual({});
    expect(parseFieldErrors("boom").fields).toEqual({});
    expect(parseFieldErrors(undefined).banner).toBeUndefined();
  });
});
