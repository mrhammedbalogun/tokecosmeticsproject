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

function Probe() {
  const { variant, status, promptChoice } = usePdp();
  return (
    <>
      <output data-testid="sku">{variant?.sku ?? "none"}</output>
      <output data-testid="stock">{variant ? String(variant.in_stock) : "-"}</output>
      <output data-testid="status">{status}</output>
      <button type="button" onClick={promptChoice}>prompt</button>
    </>
  );
}

function mount(variants: Variant[]) {
  return render(
    <PdpProvider variants={variants}>
      <VariantPicker variants={variants} />
      <Probe />
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
const sku = () => screen.getByTestId("sku").textContent;
const status = () => screen.getByTestId("status").textContent;

describe("VariantPicker — nothing is chosen for the shopper", () => {
  it("opens on a Select prompt, not on the first size", () => {
    const variants = [v({ Size: "175g" }), v({ Size: "275g" })];
    mount(variants);
    expect(combobox(/Size/).textContent).toBe("Select Size");
    expect(sku()).toBe("none");
    expect(status()).toBe("choose");
    // and no row is marked as the selection
    expect(
      within(openList(/Size/)).getAllByRole("option")
        .filter((o) => o.getAttribute("aria-selected") === "true"),
    ).toEqual([]);
  });

  it("pre-selects when there is only one thing to buy", () => {
    // Single-variant products must not make anybody pick the only option there is.
    mount([v({ Size: "175g" }), v({ Size: "275g" }, { priced: false })]);
    expect(sku()).not.toBe("none");
    expect(status()).toBe("ready");
    expect(combobox(/Size/).textContent).toBe("175g");
  });

  it("marks the axis invalid when a buy button asks for the answer", () => {
    mount([v({ Size: "175g" }), v({ Size: "275g" })]);
    expect(combobox(/Size/).getAttribute("aria-invalid")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "prompt" }));
    expect(combobox(/Size/).getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByRole("alert").textContent).toBe("Please choose a size");
    expect(combobox(/Size/)).toHaveFocus();

    fireEvent.click(within(openList(/Size/)).getByRole("option", { name: /275g/ }));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(combobox(/Size/).getAttribute("aria-invalid")).toBeNull();
  });
});

describe("VariantPicker — single axis", () => {
  it("renders a dropdown, not pills, and prices every row", () => {
    mount([
      v({ Size: "175g" }, { amount: "1800.00" }),
      v({ Size: "275g" }, { amount: "2500.00" }),
      v({ Size: "80g" }, { amount: "900.00" }),
    ]);
    expect(screen.queryByRole("button", { name: "175g" })).toBeNull();
    const trigger = combobox(/Size/);
    expect(trigger.getAttribute("aria-expanded")).toBe("false");

    const list = openList(/Size/);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    expect(optionTexts(list)).toEqual([
      "175g₦1,800.00", "275g₦2,500.00", "80g₦900.00",
    ]);
  });

  it("picking a row selects that variant and closes the list", () => {
    const variants = [v({ Size: "175g" }), v({ Size: "275g" })];
    mount(variants);
    const list = openList(/Size/);
    fireEvent.click(within(list).getByRole("option", { name: /275g/ }));
    expect(sku()).toBe(variants[1].sku);
    expect(status()).toBe("ready");
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(combobox(/Size/).textContent).toBe("275g");
    expect(
      within(openList(/Size/)).getByRole("option", { name: /275g/ })
        .getAttribute("aria-selected"),
    ).toBe("true");
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
    expect(sku()).toBe(variants[2].sku);
    expect(list).not.toBeInTheDocument();

    fireEvent.keyDown(trigger, { key: "ArrowUp" });
    expect(screen.getByRole("listbox")).toBeTruthy();
    fireEvent.keyDown(trigger, { key: "Escape" });
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(sku()).toBe(variants[2].sku);
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
    expect(sku()).toBe("none");                  // unpriced rows do nothing
    expect(screen.getByRole("listbox")).toBeTruthy();

    fireEvent.click(row(/2l/));
    expect(sku()).toBe(variants[1].sku);         // out of stock is still a choice
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

  it("reports unavailable when nothing on the product is priced here", () => {
    mount([v({ Size: "1l" }, { priced: false }), v({ Size: "2l" }, { priced: false })]);
    expect(status()).toBe("unavailable");
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

  it("answering one axis does NOT answer the other", () => {
    // The bug this replaced: picking a size landed on a concrete variant, which meant
    // silently picking that variant's colour too.
    mount([
      v({ Size: "1l", Colour: "red" }),
      v({ Size: "1l", Colour: "blue" }),
      v({ Size: "2l", Colour: "blue" }),
    ]);
    fireEvent.click(within(openList(/Size/)).getByRole("option", { name: /1l/ }));
    expect(combobox(/Size/).textContent).toBe("1l");
    expect(combobox(/Colour/).textContent).toBe("Select Colour");
    expect(sku()).toBe("none");
    expect(status()).toBe("choose");
  });

  it("resolves the variant only once every axis is answered", () => {
    const variants = [
      v({ Size: "1l", Colour: "red" }),
      v({ Size: "1l", Colour: "blue" }),
      v({ Size: "2l", Colour: "blue" }),
    ];
    mount(variants);
    fireEvent.click(within(openList(/Colour/)).getByRole("option", { name: /blue/ }));
    expect(sku()).toBe("none");
    fireEvent.click(within(openList(/Size/)).getByRole("option", { name: /1l/ }));
    expect(sku()).toBe(variants[1].sku);
    fireEvent.click(within(openList(/Size/)).getByRole("option", { name: /2l/ }));
    expect(sku()).toBe(variants[2].sku);
  });

  it("un-answers an axis a new answer cannot coexist with, instead of changing it", () => {
    const variants = [
      v({ Size: "1l", Colour: "red" }),
      v({ Size: "2l", Colour: "blue" }),
    ];
    mount(variants);
    fireEvent.click(within(openList(/Colour/)).getByRole("option", { name: /red/ }));
    fireEvent.click(within(openList(/Size/)).getByRole("option", { name: /2l/ }));
    expect(combobox(/Size/).textContent).toBe("2l");
    expect(combobox(/Colour/).textContent).toBe("Select Colour");   // NOT silently "blue"
    expect(sku()).toBe("none");
  });

  it("prices a row from the combination it would land on, and 'from' when it is open", () => {
    mount([
      v({ Size: "1l", Colour: "red" }, { amount: "1000.00" }),
      v({ Size: "1l", Colour: "blue" }, { amount: "1200.00" }),
      v({ Size: "2l", Colour: "red" }, { amount: "1900.00", in_stock: false }),
      v({ Size: "2l", Colour: "blue" }, { priced: false }),
    ]);
    // Colour unanswered: 1l could be either price, so the row says "from". 2l is
    // priced only in red and that is out of stock, so the row says so — the shopper
    // is told before the click, not after.
    expect(optionTexts(openList(/Size/))).toEqual([
      "1lfrom₦1,000.00", "2lOut of stock",
    ]);
    fireEvent.keyDown(combobox(/Size/), { key: "Escape" });
    // Answer Colour, and each size row prices exactly.
    fireEvent.click(within(openList(/Colour/)).getByRole("option", { name: /red/ }));
    expect(optionTexts(openList(/Size/))).toEqual(["1l₦1,000.00", "2lOut of stock"]);
  });
});

describe("VariantPicker — no option data", () => {
  it("lists variants by name under Options and prompts for one", () => {
    const variants = [v({}), v({})];
    variants[0].name = "Single"; variants[1].name = "Twin pack";
    mount(variants);
    expect(combobox(/Options/).textContent).toBe("Select an option");
    expect(optionTexts(openList(/Options/)).map((t) => t?.replace(/₦.*$/, ""))).toEqual([
      "Single", "Twin pack",
    ]);
    fireEvent.click(within(screen.getByRole("listbox")).getByRole("option", { name: /Twin/ }));
    expect(sku()).toBe(variants[1].sku);
    expect(combobox(/Options/).textContent).toBe("Twin pack");
  });

  it("renders nothing for a single variant", () => {
    mount([v({ Size: "1l" })]);
    expect(screen.queryByRole("combobox")).toBeNull();
  });
});

describe("PdpProvider — the newest data wins", () => {
  it("re-reads the chosen variant from the refreshed variants array", () => {
    // Add to Cart calls router.refresh() when the server says "just sold out". If the
    // provider held the Variant OBJECT it picked, the refreshed page would keep
    // insisting the thing is in stock and the shopper would keep being refused.
    const variants = [v({}), v({})];
    variants[0].name = "Single"; variants[1].name = "Twin pack";
    const { rerender } = mount(variants);
    fireEvent.click(within(openList(/Options/)).getByRole("option", { name: /Twin/ }));
    expect(screen.getByTestId("stock").textContent).toBe("true");

    const restocked = variants.map((x) => ({ ...x, in_stock: false }));
    rerender(
      <PdpProvider variants={restocked}>
        <VariantPicker variants={restocked} />
        <Probe />
      </PdpProvider>,
    );
    expect(sku()).toBe(variants[1].sku);
    expect(screen.getByTestId("stock").textContent).toBe("false");
  });
});
