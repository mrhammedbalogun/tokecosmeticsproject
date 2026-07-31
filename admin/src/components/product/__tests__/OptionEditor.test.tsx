import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { OptionEditor } from "@/components/product/OptionEditor";
import { validateAxes, type Axis } from "@/lib/variant-matrix";

/** The real production shape of toke-coco-shea-butter. */
const COCO: Axis[] = [
  { name: "Product Size", values: ["35g (sample)", "80g", "175g", "275g"] },
  { name: "Price Options", values: ["Pieces", "Pack Price"] },
];

function setup(axes: Axis[] = COCO, hasVariants = true) {
  const onChange = vi.fn();
  render(
    <OptionEditor
      axes={axes}
      errors={validateAxes(axes)}
      onChange={onChange}
      hasVariants={hasVariants}
    />,
  );
  return { onChange };
}

/** The axes the component handed back on its Nth onChange call. */
const handedBack = (onChange: ReturnType<typeof vi.fn>, call = 0): Axis[] =>
  onChange.mock.calls[call][0];

describe("OptionEditor", () => {
  it("shows the axes and their values", () => {
    setup();

    expect(screen.getByLabelText("Option 1 name")).toHaveValue("Product Size");
    expect(screen.getByLabelText("Option 2 name")).toHaveValue("Price Options");
    expect(screen.getByText("175g")).toBeInTheDocument();
    expect(screen.getByText("Pack Price")).toBeInTheDocument();
  });

  it("counts the combinations the matrix would produce", () => {
    // 4 x 2 = 8, against the 7 variants that actually exist. That gap is the point.
    setup();

    expect(screen.getByText("8 combinations")).toBeInTheDocument();
  });

  it("says nothing is saved yet, because nothing is", () => {
    setup();

    expect(screen.getByText(/saved until you generate and apply/i)).toBeInTheDocument();
  });

  it("WARNS THAT OPTION ORDER IS NOT REMEMBERED", () => {
    // Option A's accepted cost. Pretending otherwise would have somebody arrange the axes
    // and lose it on the next page load.
    setup();

    expect(screen.getByText(/not remembered after a reload/i)).toBeInTheDocument();
  });

  it("adds a value with the Add button", () => {
    const { onChange } = setup();

    fireEvent.change(screen.getByLabelText("Add a value to option 1"), {
      target: { value: "500g" },
    });
    fireEvent.click(screen.getAllByRole("button", { name: "Add" })[0]);

    expect(handedBack(onChange)[0].values).toContain("500g");
  });

  it("adds a value on Enter, because everyone tries that", () => {
    const { onChange } = setup();

    const input = screen.getByLabelText("Add a value to option 1");
    fireEvent.change(input, { target: { value: "500g" } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(handedBack(onChange)[0].values).toContain("500g");
  });

  it("ignores a blank value rather than adding an empty chip", () => {
    const { onChange } = setup();

    fireEvent.change(screen.getByLabelText("Add a value to option 1"), {
      target: { value: "   " },
    });
    fireEvent.click(screen.getAllByRole("button", { name: "Add" })[0]);

    expect(onChange).not.toHaveBeenCalled();
  });

  it("removes a value", () => {
    const { onChange } = setup();

    fireEvent.click(screen.getByLabelText("Remove 175g"));

    expect(handedBack(onChange)[0].values).not.toContain("175g");
  });

  it("reorders values, which changes the order rows are generated in", () => {
    const { onChange } = setup();

    fireEvent.click(screen.getByLabelText("Move 80g earlier"));

    expect(handedBack(onChange)[0].values.slice(0, 2)).toEqual(["80g", "35g (sample)"]);
  });

  it("REORDERS AXES, because that changes the generated NAME", () => {
    // "175g · Pack Price" vs "Pack Price · 175g" — and the name is a stored string, so the
    // order at generation time is the order that survives.
    const { onChange } = setup();

    fireEvent.click(screen.getByLabelText("Move option 2 up"));

    expect(handedBack(onChange).map((a) => a.name)).toEqual(["Price Options", "Product Size"]);
  });

  it("cannot move the first axis up or the last one down", () => {
    setup();

    expect(screen.getByLabelText("Move option 1 up")).toBeDisabled();
    expect(screen.getByLabelText("Move option 2 down")).toBeDisabled();
  });

  it("removes an axis", () => {
    const { onChange } = setup();

    fireEvent.click(screen.getByLabelText("Remove option 2"));

    expect(handedBack(onChange).map((a) => a.name)).toEqual(["Product Size"]);
  });

  it("adds an empty axis to fill in", () => {
    const { onChange } = setup();

    fireEvent.click(screen.getByRole("button", { name: "Add another option" }));

    expect(handedBack(onChange)).toHaveLength(3);
    expect(handedBack(onChange)[2]).toEqual({ name: "", values: [] });
  });

  it("renames an axis", () => {
    // The migration-debris fix: "Product Size" on 55 variants and "Size" on 12 are the
    // same axis under two WooCommerce labels.
    const { onChange } = setup();

    fireEvent.change(screen.getByLabelText("Option 1 name"), { target: { value: "Size" } });

    expect(handedBack(onChange)[0].name).toBe("Size");
  });

  it("surfaces every validation problem at once", () => {
    setup([
      { name: "", values: ["S"] },
      { name: "Shade", values: [] },
    ]);

    expect(screen.getByText(/every option needs a name/i)).toBeInTheDocument();
    expect(screen.getByText(/has no values yet/i)).toBeInTheDocument();
  });

  it("reports a matrix over the ceiling", () => {
    const huge: Axis[] = [
      { name: "A", values: Array.from({ length: 8 }, (_, i) => `a${i}`) },
      { name: "B", values: Array.from({ length: 8 }, (_, i) => `b${i}`) },
    ];

    setup(huge);

    expect(screen.getByText(/64 variants/)).toBeInTheDocument();
  });

  it("offers to start when a product has no options", () => {
    const { onChange } = setup([], false);

    expect(screen.getByText(/a single variant is the norm/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Add an option" }));
    expect(handedBack(onChange)).toEqual([{ name: "", values: [] }]);
  });

  it("says something different when variants exist but carry no option data", () => {
    // Reachable: a product could have several variants and no option_values at all.
    setup([], true);

    expect(screen.getByText(/variants but no option data/i)).toBeInTheDocument();
  });
});
