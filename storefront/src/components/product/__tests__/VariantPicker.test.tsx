import { describe, it, expect } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { VariantPicker } from "@/components/product/VariantPicker";
import { PdpProvider, usePdp } from "@/components/product/PdpContext";
import type { Variant } from "@/lib/catalog";

let nextId = 1;
const v = (
  option_values: Record<string, string>,
  { in_stock = true, priced = true, amount = "1000.00", low_stock = false } = {},
): Variant => ({
  id: nextId++, sku: `S${nextId}`, name: "test product", option_values,
  in_stock, low_stock,
  price: priced
    ? { amount, compare_at: null, currency: "NGN",
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

const combobox = (name: RegExp) => screen.getByRole("combobox", { name });
const openList = (name: RegExp) => {
  fireEvent.click(combobox(name));
  return screen.getByRole("listbox", { name });
};
const optionTexts = (list: HTMLElement) =>
  within(list).getAllByRole("option").map((o) => o.textContent);

describe("VariantPicker — single axis", () => {
  it("renders a dropdown, not pills, and prices every row", () => {
    mount([
      v({ Size: "175g", }, { amount: "1800.00" }),
      v({ Size: "275g" }, { amount: "2500.00" }),
      v({ Size: "80g" }, { amount: "900.00" }),
    ]);
    expect(screen.queryByRole("button", { name: "175g" })).toBeNull();
    const trigger = combobox(/Size/);
    expect(trigger.textContent).toBe("175g");
    expect(trigger.getAttribute("aria-expanded")).toBe("false");

    const list = openList(/Size/);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    expect(optionTexts(list)).toEqual([
      "175g₦1,800.00", "275g₦2,500.00", "80g₦900.00",
    ]);
    expect(within(list).getByRole("option", { name: /175g/ }).getAttribute("aria-selected")).toBe("true");
  });

  it("picking a row selects that variant and closes the list", () => {
    const variants = [v({ Size: "175g" }), v({ Size: "275g" })];
    mount(variants);
    const list = openList(/Size/);
    fireEvent.click(within(list).getByRole("option", { name: /275g/ }));
    expect(screen.getByTestId("sku").textContent).toBe(variants[1].sku);
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(combobox(/Size/).textContent).toBe("275g");
  });

  it("is keyboard-driven: arrows move, Enter picks, Escape closes", () => {
    const variants = [v({ Size: "175g" }), v({ Size: "275g" }), v({ Size: "80g" })];
    mount(variants);
    const trigger = combobox(/Size/);
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    const list = screen.getByRole("listbox", { name: /Size/ });
    const active = () =>
      document.getElementById(trigger.getAttribute("aria-activedescendant")!)!.textContent;
    expect(active()).toMatch(/^175g/);
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    expect(active()).toMatch(/^275g/);
    fireEvent.keyDown(trigger, { key: "End" });
    expect(active()).toMatch(/^80g/);
    fireEvent.keyDown(trigger, { key: "Enter" });
    expect(screen.getByTestId("sku").textContent).toBe(variants[2].sku);
    expect(list).not.toBeInTheDocument();

    fireEvent.keyDown(trigger, { key: "ArrowUp" });
    expect(screen.getByRole("listbox")).toBeTruthy();
    fireEvent.keyDown(trigger, { key: "Escape" });
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(screen.getByTestId("sku").textContent).toBe(variants[2].sku);
  });

  it("annotates out-of-stock rows (selectable) and disables unpriced ones", () => {
    const variants = [
      v({ Size: "1l" }),
      v({ Size: "2l" }, { in_stock: false }),
      v({ Size: "3l" }, { priced: false }),
      v({ Size: "4l" }, { low_stock: true }),
    ];
    mount(variants);
    const list = openList(/Size/);
    const row = (re: RegExp) => within(list).getByRole("option", { name: re });
    expect(row(/2l/).textContent).toBe("2lOut of stock");
    expect(row(/2l/).getAttribute("aria-disabled")).toBeNull();
    expect(row(/3l/).textContent).toBe("3lUnavailable");
    expect(row(/3l/).getAttribute("aria-disabled")).toBe("true");
    expect(row(/4l/).textContent).toBe("4lFew left₦1,000.00");

    fireEvent.click(row(/3l/));
    expect(screen.getByTestId("sku").textContent).toBe(variants[0].sku);
    expect(screen.getByRole("listbox")).toBeTruthy();

    fireEvent.click(row(/2l/));
    expect(screen.getByTestId("sku").textContent).toBe(variants[1].sku);
  });

  it("keyboard stepping skips unpriced rows", () => {
    mount([v({ Size: "1l" }), v({ Size: "2l" }, { priced: false }), v({ Size: "3l" })]);
    const trigger = combobox(/Size/);
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    expect(
      document.getElementById(trigger.getAttribute("aria-activedescendant")!)!.textContent,
    ).toMatch(/^3l/);
  });
});

describe("VariantPicker — two axes", () => {
  it("renders one labelled dropdown per axis", () => {
    mount([
      v({ Size: "1l", Colour: "red" }),
      v({ Size: "1l", Colour: "blue" }),
      v({ Size: "2l", Colour: "red" }),
      v({ Size: "2l", Colour: "blue" }),
    ]);
    expect(screen.getAllByRole("combobox")).toHaveLength(2);
    expect(optionTexts(openList(/Size/)).map((t) => t?.slice(0, 2))).toEqual(["1l", "2l"]);
    fireEvent.keyDown(combobox(/Size/), { key: "Escape" });
    expect(optionTexts(openList(/Colour/)).map((t) => t?.replace(/₦.*$/, ""))).toEqual(["red", "blue"]);
  });

  it("changing one axis keeps the other and updates the selected variant", () => {
    const variants = [
      v({ Size: "1l", Colour: "red" }),
      v({ Size: "1l", Colour: "blue" }),
      v({ Size: "2l", Colour: "blue" }),
    ];
    mount(variants);
    fireEvent.click(within(openList(/Colour/)).getByRole("option", { name: /blue/ }));
    expect(screen.getByTestId("sku").textContent).toBe(variants[1].sku);
    fireEvent.click(within(openList(/Size/)).getByRole("option", { name: /2l/ }));
    expect(screen.getByTestId("sku").textContent).toBe(variants[2].sku);
  });

  it("prices each row at the variant the combination lands on", () => {
    mount([
      v({ Size: "1l", Colour: "red" }, { amount: "1000.00" }),
      v({ Size: "2l", Colour: "red" }, { amount: "1900.00", in_stock: false }),
      v({ Size: "3l", Colour: "red" }, { priced: false }),
    ]);
    expect(optionTexts(openList(/Size/))).toEqual([
      "1l₦1,000.00", "2lOut of stock", "3lUnavailable",
    ]);
  });
});

describe("VariantPicker — no option data", () => {
  it("lists variants by name under Options", () => {
    const variants = [v({}), v({})];
    variants[0].name = "Single"; variants[1].name = "Twin pack";
    mount(variants);
    expect(optionTexts(openList(/Options/)).map((t) => t?.replace(/₦.*$/, ""))).toEqual([
      "Single", "Twin pack",
    ]);
  });

  it("renders nothing for a single variant", () => {
    mount([v({ Size: "1l" })]);
    expect(screen.queryByRole("combobox")).toBeNull();
  });
});
