import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { VariantPicker } from "@/components/product/VariantPicker";
import { PdpProvider, usePdp } from "@/components/product/PdpContext";
import type { Variant } from "@/lib/catalog";

let nextId = 1;
const v = (
  option_values: Record<string, string>,
  { in_stock = true, priced = true } = {},
): Variant => ({
  id: nextId++, sku: `S${nextId}`, name: "test product", option_values,
  in_stock, low_stock: false,
  price: priced
    ? { amount: "1000.00", compare_at: null, currency: "NGN",
        tax_rate: "0.00", prices_include_tax: true }
    : null,
});

function SelectedSku() {
  const { variant } = usePdp();
  return <output data-testid="sku">{variant?.sku ?? "none"}</output>;
}

function mount(variants: Variant[]) {
  return render(
    <PdpProvider variants={variants}>
      <VariantPicker variants={variants} />
      <SelectedSku />
    </PdpProvider>,
  );
}

describe("VariantPicker — two axes", () => {
  it("renders one labelled dropdown per axis instead of combined pills", () => {
    mount([
      v({ Size: "1l", Colour: "red" }),
      v({ Size: "1l", Colour: "blue" }),
      v({ Size: "2l", Colour: "red" }),
      v({ Size: "2l", Colour: "blue" }),
    ]);
    const size = screen.getByLabelText<HTMLSelectElement>(/Choose Size/);
    const colour = screen.getByLabelText<HTMLSelectElement>(/Choose Colour/);
    expect(Array.from(size.options).map((o) => o.value)).toEqual(["1l", "2l"]);
    expect(Array.from(colour.options).map((o) => o.value)).toEqual(["red", "blue"]);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("changing one axis keeps the other and updates the selected variant", () => {
    const variants = [
      v({ Size: "1l", Colour: "red" }),
      v({ Size: "1l", Colour: "blue" }),
      v({ Size: "2l", Colour: "blue" }),
    ];
    mount(variants);
    fireEvent.change(screen.getByLabelText(/Choose Colour/), { target: { value: "blue" } });
    expect(screen.getByTestId("sku").textContent).toBe(variants[1].sku);
    fireEvent.change(screen.getByLabelText(/Choose Size/), { target: { value: "2l" } });
    expect(screen.getByTestId("sku").textContent).toBe(variants[2].sku);
  });

  it("annotates out-of-stock options and disables unpriced ones", () => {
    mount([
      v({ Size: "1l", Colour: "red" }),
      v({ Size: "2l", Colour: "red" }, { in_stock: false }),
      v({ Size: "3l", Colour: "red" }, { priced: false }),
    ]);
    const size = screen.getByLabelText<HTMLSelectElement>(/Choose Size/);
    const byValue = Object.fromEntries(Array.from(size.options).map((o) => [o.value, o]));
    expect(byValue["2l"].textContent).toMatch(/out of stock/);
    expect(byValue["2l"].disabled).toBe(false);
    expect(byValue["3l"].textContent).toMatch(/unavailable/);
    expect(byValue["3l"].disabled).toBe(true);
  });
});

describe("VariantPicker — single axis", () => {
  it("keeps the pill buttons", () => {
    mount([v({ Size: "175g" }), v({ Size: "500g" })]);
    expect(screen.getByRole("button", { name: "175g" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "500g" })).toBeTruthy();
    expect(screen.queryByRole("combobox")).toBeNull();
  });
});
