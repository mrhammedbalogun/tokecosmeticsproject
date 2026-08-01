import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { InventoryGrid } from "@/components/inventory/InventoryGrid";
import type { GridCell, GridRow } from "@/lib/inventory";

const adjust = vi.fn<(input: unknown) => Promise<{ ok: boolean }>>(async () => ({ ok: true }));
vi.mock("@/app/(shell)/inventory/actions", () => ({
  adjustStockAction: (input: unknown) => adjust(input),
}));

const cell = (over: Partial<GridCell> = {}): GridCell => ({
  warehouse_id: 1,
  warehouse_name: "Lagos HQ",
  stock_item_id: 10,
  quantity: 40,
  reserved: 0,
  available: 40,
  low_stock_threshold: 5,
  is_low: false,
  ...over,
});

const row = (over: Partial<GridRow> = {}): GridRow => ({
  variant_id: 1,
  sku: "TOKE-SHEA-200",
  variant_name: "200g",
  product_name: "Shea Whip Body Butter",
  product_slug: "shea-whip-body-butter",
  cells: [cell()],
  ...over,
});

const WAREHOUSES = [{ id: 1, name: "Lagos HQ" }];

beforeEach(() => adjust.mockClear());

describe("InventoryGrid", () => {
  it("RENDERS AN ABSENT CELL AS AN ABSENCE, not as a blank or a zero", () => {
    // Ruling 3. Every other screen lists stock ROWS, so an absent row has nothing to
    // list — this is the only place the gap is visible at all.
    render(
      <InventoryGrid
        rows={[row({ cells: [cell({ stock_item_id: null, quantity: null, available: null })] })]}
        warehouses={WAREHOUSES}
      />,
    );

    expect(screen.getByText("Not stocked")).toBeInTheDocument();
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });

  it("offers no adjust control on a cell that has no row to adjust", () => {
    render(
      <InventoryGrid
        rows={[row({ cells: [cell({ stock_item_id: null, quantity: null })] })]}
        warehouses={WAREHOUSES}
      />,
    );

    expect(screen.queryByRole("button", { name: /adjust/i })).not.toBeInTheDocument();
  });

  it("marks a low cell and still shows its real count", () => {
    render(
      <InventoryGrid
        rows={[row({ cells: [cell({ quantity: 3, is_low: true })] })]}
        warehouses={WAREHOUSES}
      />,
    );

    // Scoped to the cell control: the row total legitimately reads 3 as well.
    const control = screen.getByRole("button", { name: /3/ });
    expect(control).toHaveTextContent("3");
    expect(within(control).getByText("Low")).toBeInTheDocument();
  });

  it("totals only what has been counted", () => {
    render(
      <InventoryGrid
        rows={[
          row({
            cells: [
              cell({ quantity: 40 }),
              cell({ warehouse_id: 2, warehouse_name: "UK", stock_item_id: null, quantity: null }),
            ],
          }),
        ]}
        warehouses={[...WAREHOUSES, { id: 2, name: "UK" }]}
      />,
    );

    // 40, not 40-plus-a-zero-nobody-counted.
    const cells = screen.getAllByRole("cell");
    expect(cells[cells.length - 1]).toHaveTextContent("40");
  });

  it("opens the adjust modal on a counted cell and sends the stock row's id", () => {
    render(<InventoryGrid rows={[row()]} warehouses={WAREHOUSES} />);

    fireEvent.click(screen.getByRole("button", { name: /40/ }));

    const dialog = screen.getByText("New quantity").closest("form") ?? document.body;
    fireEvent.change(within(dialog).getByLabelText(/new quantity/i), {
      target: { value: "12" },
    });
    fireEvent.change(within(dialog).getByLabelText(/note/i), {
      target: { value: "counted the shelf" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: /save|adjust/i }));

    expect(adjust).toHaveBeenCalledWith(
      expect.objectContaining({ stockItemId: 10, quantity: 12, note: "counted the shelf" }),
    );
  });

  it("says so when a filter matches nothing", () => {
    render(<InventoryGrid rows={[]} warehouses={WAREHOUSES} />);

    expect(screen.getByText("No variants match this filter.")).toBeInTheDocument();
  });
});
