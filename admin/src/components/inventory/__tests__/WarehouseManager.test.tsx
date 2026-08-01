import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { WarehouseManager } from "@/components/inventory/WarehouseManager";
import type { WarehouseRow } from "@/lib/warehouses";

const save = vi.fn<(input: unknown) => Promise<{ savedAt?: number }>>(async () => ({
  savedAt: 1,
}));
vi.mock("@/app/(shell)/inventory/warehouses/actions", () => ({
  saveWarehouseAction: (input: unknown) => save(input),
}));

/** Production as measured 2026-07-31: both active, both at priority 1. */
const LAGOS: WarehouseRow = {
  id: 1,
  name: "Lagos HQ",
  location_country: "NG",
  serves_countries: ["NG", "ZZ"],
  priority: 1,
  is_active: true,
  countries_left_unserved: ["NG"],
};
const UK: WarehouseRow = {
  id: 2,
  name: "UK Warehouse",
  location_country: "GB",
  serves_countries: ["GB", "US", "CA", "ZZ"],
  priority: 1,
  is_active: true,
  countries_left_unserved: ["GB", "US", "CA"],
};

const COUNTRIES = [
  { code: "NG", name: "Nigeria" },
  { code: "GB", name: "United Kingdom" },
  { code: "US", name: "United States" },
  { code: "CA", name: "Canada" },
  { code: "ZZ", name: "International" },
];

const setup = (warehouses = [LAGOS, UK]) =>
  render(<WarehouseManager warehouses={warehouses} countries={COUNTRIES} />);

beforeEach(() => {
  save.mockClear();
  save.mockResolvedValue({ savedAt: 1 });
});

describe("WarehouseManager", () => {
  it("WARNS about a shared priority rather than merely printing it", () => {
    // Two identical numbers nobody chose do not tell anyone a decision is owed.
    setup();

    const warning = screen.getByRole("alert");
    expect(warning).toHaveTextContent("Lagos HQ and UK Warehouse");
    expect(warning).toHaveTextContent("share priority 1");
    expect(warning).toHaveTextContent("whichever was created first");
  });

  it("drops the warning once the priorities differ", () => {
    setup([LAGOS, { ...UK, priority: 2 }]);

    expect(screen.queryByText(/share priority/)).not.toBeInTheDocument();
  });

  it("ignores an inactive warehouse when looking for a tie", () => {
    setup([LAGOS, { ...UK, is_active: false }]);

    expect(screen.queryByText(/share priority/)).not.toBeInTheDocument();
  });

  it("SAVES A HARMLESS EDIT WITHOUT A CONFIRMATION", () => {
    // Renaming cannot strand anybody, so it must not be gated — a confirmation that
    // fires on everything is one nobody reads.
    setup();

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Lagos Main" } });
    fireEvent.click(screen.getByRole("button", { name: /save warehouse/i }));

    expect(save).toHaveBeenCalledWith(expect.objectContaining({ id: 1, name: "Lagos Main" }));
  });

  it("REFUSES TO SEND AN EDIT THAT STRANDS A MARKET UNTIL IT IS CONFIRMED IN WORDS", () => {
    // Ruling 1b. Unticking NG on Lagos HQ removes the only warehouse serving Nigeria.
    setup();

    fireEvent.click(screen.getByLabelText(/Nigeria/));
    fireEvent.click(screen.getByRole("button", { name: /save warehouse/i }));

    expect(save).not.toHaveBeenCalled();
    expect(screen.getByText("Nigeria will have no warehouse.")).toBeInTheDocument();
    expect(screen.getByText(/Checkout will fail there/)).toBeInTheDocument();
  });

  it("sends it once the operator says so", () => {
    setup();
    fireEvent.click(screen.getByLabelText(/Nigeria/));
    fireEvent.click(screen.getByRole("button", { name: /save warehouse/i }));

    fireEvent.click(screen.getByRole("button", { name: /save anyway/i }));

    expect(save).toHaveBeenCalledWith(
      expect.objectContaining({ id: 1, serves_countries: ["ZZ"] }),
    );
  });

  it("lets the operator back out, sending nothing", () => {
    setup();
    fireEvent.click(screen.getByLabelText(/Nigeria/));
    fireEvent.click(screen.getByRole("button", { name: /save warehouse/i }));

    fireEvent.click(screen.getByRole("button", { name: /^cancel$/i }));

    expect(save).not.toHaveBeenCalled();
    expect(screen.queryByText("Nigeria will have no warehouse.")).not.toBeInTheDocument();
  });

  it("GATES DEACTIVATION TOO, naming every market it would strand", () => {
    setup();

    fireEvent.click(screen.getByLabelText(/Active/));
    fireEvent.click(screen.getByRole("button", { name: /save warehouse/i }));

    expect(save).not.toHaveBeenCalled();
    expect(screen.getByText("Nigeria will have no warehouse.")).toBeInTheDocument();
  });

  it("does not gate dropping a country another active warehouse still covers", () => {
    // ZZ is served by both, so Lagos dropping it strands nobody.
    setup();

    fireEvent.click(screen.getByLabelText(/International/));
    fireEvent.click(screen.getByRole("button", { name: /save warehouse/i }));

    expect(save).toHaveBeenCalledWith(
      expect.objectContaining({ serves_countries: ["NG"] }),
    );
  });
});
