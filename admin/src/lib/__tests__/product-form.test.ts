import { describe, it, expect } from "vitest";
import {
  EDITABLE_FIELDS,
  isDirty,
  normaliseFaqs,
  normaliseSpecs,
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
  ingredients: "",
  directions: "",
  warnings: "",
  specs: [],
  faqs: [],
  seo_title: "",
  seo_description: "",
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

describe("normaliseSpecs / normaliseFaqs", () => {
  it("keeps a half-populated row instead of discarding it", () => {
    // These are JSONFields holding whatever the WordPress importer produced for 69
    // migrated products. Dropping a partial row would delete migrated content on the next
    // save of an unrelated tab — the quietest kind of data loss.
    expect(normaliseSpecs([{ label: "Size" }])).toEqual([{ label: "Size", value: "" }]);
    expect(normaliseFaqs([{ q: "Is it oily?" }])).toEqual([{ q: "Is it oily?", a: "" }]);
  });

  it("coerces a number or boolean into the string the input needs", () => {
    // Meaningful content badly typed, not garbage. A raw number in a controlled input
    // makes React switch the field to uncontrolled mid-edit.
    expect(normaliseSpecs([{ label: "Weight", value: 250 }])).toEqual([
      { label: "Weight", value: "250" },
    ]);
  });

  it("discards entries that are not objects, because there is no field to show them in", () => {
    expect(normaliseSpecs(["nonsense", null, 7])).toEqual([]);
  });

  it("returns an empty list for anything that is not an array", () => {
    expect(normaliseSpecs(null)).toEqual([]);
    expect(normaliseSpecs({ label: "x" })).toEqual([]);
    expect(normaliseFaqs(undefined)).toEqual([]);
  });
});

describe("toPatchPayload — content rows", () => {
  it("drops rows nobody filled in", () => {
    const payload = toPatchPayload(
      values({
        specs: [
          { label: "Size", value: "250ml" },
          { label: "", value: "" },
        ],
        faqs: [{ q: "", a: "" }],
      }),
    );

    expect(payload.specs).toEqual([{ label: "Size", value: "250ml" }]);
    expect(payload.faqs).toEqual([]);
  });

  it("KEEPS a half-filled row, because it is work in progress", () => {
    // A question typed but not yet answered is not an empty row. Silently discarding it
    // would lose what somebody just wrote.
    const payload = toPatchPayload(values({ faqs: [{ q: "Is it oily?", a: "" }] }));

    expect(payload.faqs).toEqual([{ q: "Is it oily?", a: "" }]);
  });
});

describe("isDirty — ordered content rows", () => {
  it("notices a reordered spec table", () => {
    // specs and faqs are ORDERED rows, unlike the checkbox sets. A reorder is a real edit,
    // and calling it none would leave it unsaved with the bar saying there was nothing.
    const a = values({
      specs: [
        { label: "A", value: "1" },
        { label: "B", value: "2" },
      ],
    });
    const b = values({
      specs: [
        { label: "B", value: "2" },
        { label: "A", value: "1" },
      ],
    });

    expect(isDirty(a, b)).toBe(true);
  });

  it("does not arm Save for an empty row that was added and abandoned", () => {
    // The row is dropped on the way out anyway, so offering to save it would promise a
    // change that cannot happen — and the bar would never clear.
    const a = values({ specs: [{ label: "A", value: "1" }] });
    const b = values({
      specs: [
        { label: "A", value: "1" },
        { label: "", value: "" },
      ],
    });

    expect(isDirty(a, b)).toBe(false);
  });

  it("notices a real edit inside a row", () => {
    const a = values({ specs: [{ label: "Size", value: "250ml" }] });
    const b = values({ specs: [{ label: "Size", value: "500ml" }] });

    expect(isDirty(a, b)).toBe(true);
  });

  it("notices edited prose and SEO fields", () => {
    expect(isDirty(values(), values({ ingredients: "Shea butter" }))).toBe(true);
    expect(isDirty(values(), values({ seo_title: "Best shea" }))).toBe(true);
  });
});
