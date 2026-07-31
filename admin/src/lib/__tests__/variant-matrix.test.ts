import { describe, it, expect } from "vitest";
import {
  cartesian,
  deriveAxes,
  diffMatrix,
  MAX_COMBINATIONS,
  suggestSku,
  validateAxes,
  variantName,
  type Axis,
  type MatrixVariant,
} from "@/lib/variant-matrix";

const v = (id: number, options: Record<string, string>, sku = `SKU-${id}`): MatrixVariant => ({
  id,
  sku,
  name: "Toke coco shea butter",
  option_values: options,
});

/** The real shape of `toke-coco-shea-butter` in production: seven variants over a
 *  4 × 2 grid, which is INCOMPLETE — 35g exists only as Pieces. */
const COCO: MatrixVariant[] = [
  v(1, { "Product Size": "35g (sample)", "Price Options": "Pieces" }),
  v(2, { "Product Size": "80g", "Price Options": "Pack Price" }),
  v(3, { "Product Size": "80g", "Price Options": "Pieces" }),
  v(4, { "Product Size": "175g", "Price Options": "Pieces" }),
  v(5, { "Product Size": "175g", "Price Options": "Pack Price" }),
  v(6, { "Product Size": "275g", "Price Options": "Pieces" }),
  v(7, { "Product Size": "275g", "Price Options": "Pack Price" }),
];

/** One axis, the common production case — 10 of the 18 multi-variant products. */
const ONE_AXIS: MatrixVariant[] = [
  v(1, { Size: "100ml" }),
  v(2, { Size: "250ml" }),
];

describe("deriveAxes", () => {
  it("reads both axes and their values off the variants", () => {
    const axes = deriveAxes(COCO);

    expect(axes.map((a) => a.name)).toEqual(["Product Size", "Price Options"]);
    expect(axes[0].values).toEqual(["35g (sample)", "80g", "175g", "275g"]);
    expect(axes[1].values).toEqual(["Pieces", "Pack Price"]);
  });

  it("lists each value once however many variants use it", () => {
    // 80g appears twice in COCO — once per price option.
    expect(deriveAxes(COCO)[0].values.filter((x) => x === "80g")).toHaveLength(1);
  });

  it("handles the single-axis case", () => {
    expect(deriveAxes(ONE_AXIS)).toEqual([{ name: "Size", values: ["100ml", "250ml"] }]);
  });

  it("returns nothing for a product with no option data", () => {
    // 52 production variants — every single-variant product. The master spec says these
    // skip the builder entirely.
    expect(deriveAxes([v(1, {})])).toEqual([]);
    expect(deriveAxes([])).toEqual([]);
  });

  it("collects an axis only some variants carry", () => {
    const axes = deriveAxes([v(1, { Size: "S" }), v(2, { Shade: "Fair" })]);

    expect(axes.map((a) => a.name)).toEqual(["Size", "Shade"]);
  });

  it("is stable across calls, so the builder does not reshuffle under a user", () => {
    expect(deriveAxes(COCO)).toEqual(deriveAxes(COCO));
  });
});

describe("cartesian", () => {
  it("produces every combination", () => {
    const axes: Axis[] = [
      { name: "Size", values: ["S", "M"] },
      { name: "Shade", values: ["Fair", "Deep"] },
    ];

    expect(cartesian(axes)).toEqual([
      { Size: "S", Shade: "Fair" },
      { Size: "S", Shade: "Deep" },
      { Size: "M", Shade: "Fair" },
      { Size: "M", Shade: "Deep" },
    ]);
  });

  it("varies the LAST axis fastest, so the first axis reads as the grouping", () => {
    const out = cartesian([
      { name: "Size", values: ["S", "M"] },
      { name: "Shade", values: ["A", "B"] },
    ]);

    expect(out.map((c) => c.Size)).toEqual(["S", "S", "M", "M"]);
  });

  it("handles one axis", () => {
    expect(cartesian([{ name: "Size", values: ["S", "M"] }])).toEqual([
      { Size: "S" },
      { Size: "M" },
    ]);
  });

  it("is empty when there are no axes", () => {
    expect(cartesian([])).toEqual([]);
  });

  it("is empty when any axis has no values, because no combination can be formed", () => {
    expect(cartesian([{ name: "Size", values: [] }])).toEqual([]);
    expect(
      cartesian([
        { name: "Size", values: ["S"] },
        { name: "Shade", values: [] },
      ]),
    ).toEqual([]);
  });

  it("reproduces the full grid for the production product", () => {
    // 4 x 2 = 8, against the 7 variants that actually exist — the missing one is the point.
    expect(cartesian(deriveAxes(COCO))).toHaveLength(8);
  });
});

describe("diffMatrix", () => {
  it("finds the one combination production is missing", () => {
    // 35g exists only as Pieces; 35g x Pack Price has never existed.
    const { existing, missing, orphaned } = diffMatrix(cartesian(deriveAxes(COCO)), COCO);

    expect(existing).toHaveLength(7);
    expect(missing).toEqual([{ "Product Size": "35g (sample)", "Price Options": "Pack Price" }]);
    expect(orphaned).toEqual([]);
  });

  it("matches regardless of key order, because jsonb does not preserve it", () => {
    const combination = { "Price Options": "Pieces", "Product Size": "80g" };

    const { existing } = diffMatrix([combination], COCO);

    expect(existing).toHaveLength(1);
  });

  it("reports a variant outside the matrix as orphaned, never as missing", () => {
    const axes: Axis[] = [{ name: "Size", values: ["100ml"] }];

    const { missing, orphaned } = diffMatrix(cartesian(axes), ONE_AXIS);

    expect(missing).toEqual([]);
    expect(orphaned.map((o) => o.id)).toEqual([2]); // the 250ml
  });

  it("ORPHANS EVERY EXISTING VARIANT WHEN AN AXIS IS ADDED", () => {
    // A consequence worth pinning rather than discovering. A variant with {Size: 100ml}
    // does not match {Size: 100ml, Shade: Fair} — it has no value for the new axis, and
    // guessing one would invent data. Apply never deletes, so nothing is lost; but the UI
    // must say this before somebody creates a parallel set of variants.
    const axes: Axis[] = [
      { name: "Size", values: ["100ml", "250ml"] },
      { name: "Shade", values: ["Fair"] },
    ];

    const { missing, orphaned } = diffMatrix(cartesian(axes), ONE_AXIS);

    expect(missing).toHaveLength(2);
    expect(orphaned).toHaveLength(2);
  });

  it("ignores variants with no option data at all", () => {
    const { orphaned } = diffMatrix(cartesian(deriveAxes(ONE_AXIS)), [...ONE_AXIS, v(9, {})]);

    expect(orphaned.map((o) => o.id)).toEqual([9]);
  });

  it("does not match a variant carrying an EXTRA axis", () => {
    const combination = { Size: "100ml" };
    const richer = [v(1, { Size: "100ml", Shade: "Fair" })];

    const { existing, orphaned } = diffMatrix([combination], richer);

    expect(existing).toEqual([]);
    expect(orphaned).toHaveLength(1);
  });
});

describe("variantName", () => {
  it("joins the values, matching the storefront's picker label", () => {
    // storefront/src/lib/variant-label.ts joins with the same separator. A generated name
    // that disagreed would show one thing in admin and another on the PDP.
    expect(variantName({ "Product Size": "175g", "Price Options": "Pack Price" })).toBe(
      "175g · Pack Price",
    );
  });

  it("handles a single axis", () => {
    expect(variantName({ Size: "250ml" })).toBe("250ml");
  });

  it("is empty for an empty combination, so the caller must decide a fallback", () => {
    expect(variantName({})).toBe("");
  });
});

describe("suggestSku", () => {
  it("builds a slug-shaped sku from the product and the values", () => {
    expect(suggestSku("toke-coco-shea-butter", { "Product Size": "175g" }, [])).toBe(
      "toke-coco-shea-butter-175g",
    );
  });

  it("joins multiple values", () => {
    const sku = suggestSku(
      "orange-shower-gel",
      { "Product Size": "250ml", "Price Options": "Pack Price" },
      [],
    );

    expect(sku).toBe("orange-shower-gel-250ml-pack-price");
  });

  it("strips punctuation that would not survive in a sku", () => {
    expect(suggestSku("p", { Size: "35g (sample)" }, [])).toBe("p-35g-sample");
  });

  it("DE-DUPLICATES against skus already taken", () => {
    // `ProductVariant.sku` is unique across the whole table, so a collision is a 400 from
    // the backend on Apply. Cheaper to avoid than to explain.
    const taken = ["p-175g"];

    expect(suggestSku("p", { Size: "175g" }, taken)).toBe("p-175g-2");
  });

  it("keeps counting past the first duplicate", () => {
    expect(suggestSku("p", { Size: "175g" }, ["p-175g", "p-175g-2"])).toBe("p-175g-3");
  });

  it("NEVER EXCEEDS THE COLUMN, which is 64 characters", () => {
    // ProductVariant.sku is CharField(max_length=64). A longer suggestion is a guaranteed
    // 400 that looks like a bug in the builder.
    const long = "a-very-long-product-slug-that-goes-on-and-on-for-quite-some-while";
    const sku = suggestSku(long, { Size: "500ml", Shade: "Something Long Here" }, []);

    expect(sku.length).toBeLessThanOrEqual(64);
  });

  it("stays unique even when truncation would have collided", () => {
    const long = "a-very-long-product-slug-that-goes-on-and-on-for-quite-some-while";
    const first = suggestSku(long, { Size: "500ml" }, []);
    const second = suggestSku(long, { Size: "500ml" }, [first]);

    expect(second).not.toBe(first);
    expect(second.length).toBeLessThanOrEqual(64);
  });
});

describe("validateAxes", () => {
  const ok: Axis[] = [{ name: "Size", values: ["S", "M"] }];

  it("passes a sane set", () => {
    expect(validateAxes(ok)).toEqual([]);
  });

  it("rejects a blank axis name", () => {
    expect(validateAxes([{ name: "  ", values: ["S"] }])[0]).toMatch(/name/i);
  });

  it("rejects two axes with the same name", () => {
    // They would collapse into one key on write, silently losing an axis.
    const errors = validateAxes([
      { name: "Size", values: ["S"] },
      { name: "Size", values: ["M"] },
    ]);

    expect(errors[0]).toMatch(/twice|duplicate|same/i);
  });

  it("treats names differing only by case or padding as the same", () => {
    const errors = validateAxes([
      { name: "Size", values: ["S"] },
      { name: " size ", values: ["M"] },
    ]);

    expect(errors).not.toEqual([]);
  });

  it("rejects an axis with no values", () => {
    expect(validateAxes([{ name: "Size", values: [] }])[0]).toMatch(/value/i);
  });

  it("rejects a blank value", () => {
    expect(validateAxes([{ name: "Size", values: ["S", " "] }])[0]).toMatch(/blank|empty/i);
  });

  it("rejects a repeated value within one axis", () => {
    expect(validateAxes([{ name: "Size", values: ["S", "S"] }])[0]).toMatch(/twice|duplicate/i);
  });

  it("REFUSES A MATRIX BIGGER THAN THE CEILING", () => {
    // Three axes of five values is 125 variants, each with price and stock rows, created
    // by 125 sequential POSTs. Nothing in production approaches this — the ceiling exists
    // because a builder puts it one careless click away.
    const huge: Axis[] = [
      { name: "A", values: ["1", "2", "3", "4", "5"] },
      { name: "B", values: ["1", "2", "3", "4", "5"] },
      { name: "C", values: ["1", "2", "3", "4", "5"] },
    ];

    expect(validateAxes(huge).join(" ")).toMatch(new RegExp(String(MAX_COMBINATIONS)));
  });

  it("allows a matrix exactly at the ceiling", () => {
    const atLimit: Axis[] = [
      { name: "A", values: Array.from({ length: 10 }, (_, i) => `a${i}`) },
      { name: "B", values: Array.from({ length: 5 }, (_, i) => `b${i}`) },
    ];

    expect(validateAxes(atLimit)).toEqual([]);
  });

  it("passes the real production matrix comfortably", () => {
    expect(validateAxes(deriveAxes(COCO))).toEqual([]);
  });
});
