import { describe, it, expect } from "vitest";
import { positionWrites, reorder, sortImages } from "@/lib/product-images";

const img = (id: number, position: number) => ({ id, position });

describe("reorder", () => {
  it("moves a row up and renumbers from zero", () => {
    const out = reorder([img(1, 0), img(2, 1), img(3, 2)], 2, 0);

    expect(out.map((i) => i.id)).toEqual([3, 1, 2]);
    expect(out.map((i) => i.position)).toEqual([0, 1, 2]);
  });

  it("moves a row down", () => {
    const out = reorder([img(1, 0), img(2, 1), img(3, 2)], 0, 2);

    expect(out.map((i) => i.id)).toEqual([2, 3, 1]);
  });

  it("RENUMBERS RATHER THAN SWAPPING, so duplicate positions still reorder", () => {
    // `position` has no uniqueness constraint and the 69 migrated products were populated
    // by an importer, so [0,0,0] is possible. A swap of two equal numbers changes nothing
    // and the row springs back on reload with no error anywhere.
    const out = reorder([img(1, 0), img(2, 0), img(3, 0)], 2, 0);

    expect(out.map((i) => i.id)).toEqual([3, 1, 2]);
    expect(out.map((i) => i.position)).toEqual([0, 1, 2]);
  });

  it("closes gaps left by an importer", () => {
    const out = reorder([img(1, 5), img(2, 40)], 1, 0);

    expect(out.map((i) => i.position)).toEqual([0, 1]);
  });

  it("is a no-op for an out-of-range move rather than throwing", () => {
    // Double-clicking "down" on the last row is a no-op, not an error.
    const list = [img(1, 0), img(2, 1)];

    expect(reorder(list, 1, 2)).toBe(list);
    expect(reorder(list, -1, 0)).toBe(list);
    expect(reorder(list, 0, 0)).toBe(list);
  });
});

describe("positionWrites", () => {
  it("names only the rows whose number actually moved", () => {
    const before = [img(1, 0), img(2, 1), img(3, 2)];
    const after = reorder(before, 0, 1);

    // A one-step swap should cost two PATCHes, not one per image.
    expect(positionWrites(before, after)).toEqual([
      { id: 2, position: 0 },
      { id: 1, position: 1 },
    ]);
  });

  it("writes every row when the list was never numbered properly", () => {
    const before = [img(1, 0), img(2, 0), img(3, 0)];
    const after = reorder(before, 2, 0);

    expect(positionWrites(before, after)).toHaveLength(2);
  });

  it("is empty when nothing moved", () => {
    const list = [img(1, 0), img(2, 1)];

    expect(positionWrites(list, list)).toEqual([]);
  });
});

describe("sortImages", () => {
  it("orders by position", () => {
    expect(sortImages([img(1, 2), img(2, 0), img(3, 1)]).map((i) => i.id)).toEqual([2, 3, 1]);
  });

  it("breaks a tie by id, exactly as the model's Meta.ordering does", () => {
    // ProductImage.Meta.ordering = ["position", "id"]. A UI that resolved ties differently
    // would show a gallery order nobody else sees, including the storefront.
    expect(sortImages([img(9, 0), img(2, 0)]).map((i) => i.id)).toEqual([2, 9]);
  });

  it("does not mutate its input", () => {
    const list = [img(2, 1), img(1, 0)];
    sortImages(list);

    expect(list.map((i) => i.id)).toEqual([2, 1]);
  });
});
