import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { InventoryGrid } from "@/components/inventory/InventoryGrid";
import type { GridCell, GridRow } from "@/lib/inventory";

const adjust = vi.fn<(input: unknown) => Promise<{ ok: boolean }>>(async () => ({ ok: true }));
const startStocking = vi.fn<
  (input: unknown) => Promise<{ ok?: boolean; partial?: boolean; message?: string | null }>
>(async () => ({ ok: true }));
vi.mock("@/app/(shell)/inventory/actions", () => ({
  adjustStockAction: (input: unknown) => adjust(input),
  startStockingAction: (input: unknown) => startStocking(input),
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

beforeEach(() => {
  adjust.mockClear();
  startStocking.mockClear();
  startStocking.mockResolvedValue({ ok: true });
});

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

  it("makes the absence ACTIONABLE — it opens the start-stocking form", () => {
    // 17a Task 7 recorded that there was no admin path to start stocking a variant in a
    // second warehouse at all. This click is that path.
    render(
      <InventoryGrid
        rows={[row({ cells: [cell({ stock_item_id: null, quantity: null })] })]}
        warehouses={WAREHOUSES}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Not stocked" }));

    expect(screen.getByText("Start stocking here")).toBeInTheDocument();
  });

  it("creates the row with the opening count, the threshold and the reason", () => {
    render(
      <InventoryGrid
        rows={[row({ cells: [cell({ stock_item_id: null, quantity: null })] })]}
        warehouses={WAREHOUSES}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Not stocked" }));

    fireEvent.change(screen.getByLabelText(/opening count/i), { target: { value: "40" } });
    fireEvent.change(screen.getByLabelText(/low-stock threshold/i), { target: { value: "8" } });
    fireEvent.change(screen.getByLabelText(/note/i), { target: { value: "opening the UK shelf" } });
    fireEvent.click(screen.getByRole("button", { name: /start stocking/i }));

    expect(startStocking).toHaveBeenCalledWith({
      variantId: 1,
      warehouseId: 1,
      quantity: 40,
      threshold: 8,
      reason: "restock",
      note: "opening the UK shelf",
    });
  });

  it("ASKS FOR NO REASON WHEN THE OPENING COUNT IS ZERO", () => {
    // Nothing moved, so there is no movement to explain — and demanding a note for a 0
    // would train people to type "n/a" into the field the ledger depends on.
    render(
      <InventoryGrid
        rows={[row({ cells: [cell({ stock_item_id: null, quantity: null })] })]}
        warehouses={WAREHOUSES}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Not stocked" }));

    expect(screen.queryByLabelText(/note/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/reason/i)).not.toBeInTheDocument();
  });

  it("closes and reports on the grid when the row was created but the count was not", async () => {
    // The row EXISTS now, so reopening the form would meet a duplicate error.
    startStocking.mockResolvedValue({
      partial: true,
      message: "The row was created but the opening count was not recorded.",
    });
    render(
      <InventoryGrid
        rows={[row({ cells: [cell({ stock_item_id: null, quantity: null })] })]}
        warehouses={WAREHOUSES}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Not stocked" }));
    fireEvent.change(screen.getByLabelText(/opening count/i), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText(/note/i), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: /start stocking/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("was created but");
    expect(screen.queryByText("Start stocking here")).not.toBeInTheDocument();
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
