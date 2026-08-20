import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { DeliveryControls } from "@/components/config/DeliveryControls";
import type {
  DeliveryBlockRow,
  DeliveryFeeMaskRow,
  DeliveryServiceRef,
} from "@/lib/delivery-controls";
import type { RegionRow } from "@/lib/regions";
import type { CountryRef } from "@/lib/reference";

const createBlockAction = vi.fn();
const createMaskAction = vi.fn();
vi.mock("@/app/(shell)/settings/delivery-controls/actions", () => ({
  createBlockAction: (...args: unknown[]) => createBlockAction(...args),
  saveBlockAction: vi.fn(),
  deleteBlockAction: vi.fn(),
  createMaskAction: (...args: unknown[]) => createMaskAction(...args),
  saveMaskAction: vi.fn(),
  deleteMaskAction: vi.fn(),
}));

const SERVICES: DeliveryServiceRef[] = [
  { code: "gig", name: "GIG Logistics", kind: "carrier" },
  { code: "brandnpack", name: "BrandnPack", kind: "partner" },
  { code: "store_pickup", name: "Pickup at Toke Cosmetics Store", kind: "store" },
];

const COUNTRIES: CountryRef[] = [
  {
    code: "NG",
    name: "Nigeria",
    is_default: true,
    is_rest_of_world: false,
    state_label: "State",
    area_label: "LGA",
  },
];

const REGIONS: RegionRow[] = [
  { id: 1, country_code: "NG", name: "Lagos", level: "state", parent: null, is_active: true },
  { id: 2, country_code: "NG", name: "Ikeja", level: "area", parent: 1, is_active: true },
];

const BLOCK: DeliveryBlockRow = {
  id: 7,
  service_code: "gig",
  service_name: "GIG Logistics",
  country_code: "NG",
  state_region: 1,
  state_name: "Lagos",
  area_region: 2,
  area_name: "Ikeja",
  is_active: true,
  updated_at: "2026-08-20T00:00:00Z",
};

const MASK: DeliveryFeeMaskRow = {
  id: 3,
  service_code: "gig",
  service_name: "GIG Logistics",
  percent: "10.00",
  is_active: true,
  updated_at: "2026-08-20T00:00:00Z",
};

beforeEach(() => {
  createBlockAction.mockReset().mockResolvedValue({ savedAt: 1 });
  createMaskAction.mockReset().mockResolvedValue({ savedAt: 1 });
});

describe("DeliveryControls", () => {
  it("renders a block rule with its full place path", () => {
    render(
      <DeliveryControls
        services={SERVICES}
        blocks={[BLOCK]}
        masks={[]}
        countries={COUNTRIES}
        regions={REGIONS}
      />,
    );
    expect(screen.getByText("Nigeria → Lagos → Ikeja")).toBeInTheDocument();
    expect(screen.getByText("blocking")).toBeInTheDocument();
  });

  it("cascades the pickers and submits a whole-state block with a null LGA", async () => {
    render(
      <DeliveryControls
        services={SERVICES}
        blocks={[]}
        masks={[]}
        countries={COUNTRIES}
        regions={REGIONS}
      />,
    );

    // Two "Delivery service" selects exist (block form + mask form) — the first
    // belongs to the block form.
    fireEvent.change(screen.getAllByLabelText("Delivery service")[0], {
      target: { value: "gig" },
    });
    fireEvent.change(screen.getByLabelText("State"), { target: { value: "1" } });
    expect(screen.getByText("Blocked across the whole state.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /block it/i }));
    await waitFor(() =>
      expect(createBlockAction).toHaveBeenCalledWith({
        service_code: "gig",
        country_code: "NG",
        state_region: 1,
        area_region: null,
      }),
    );
  });

  it("submits a new mask and hides already-masked services from the picker", async () => {
    render(
      <DeliveryControls
        services={SERVICES}
        blocks={[]}
        masks={[MASK]}
        countries={COUNTRIES}
        regions={REGIONS}
      />,
    );

    // GIG already carries a mask, so the add form must not offer it again.
    const maskSelect = screen.getAllByLabelText("Delivery service").at(-1)!;
    expect(
      within(maskSelect as HTMLElement).queryByText(/GIG Logistics/),
    ).not.toBeInTheDocument();

    fireEvent.change(maskSelect, { target: { value: "brandnpack" } });
    fireEvent.change(screen.getByPlaceholderText("10"), { target: { value: "15" } });
    fireEvent.click(screen.getByRole("button", { name: /add mask/i }));

    await waitFor(() =>
      expect(createMaskAction).toHaveBeenCalledWith({
        service_code: "brandnpack",
        percent: "15",
      }),
    );
  });

  it("explains the maths in the fee-masking blurb", () => {
    render(
      <DeliveryControls
        services={SERVICES}
        blocks={[]}
        masks={[]}
        countries={COUNTRIES}
        regions={REGIONS}
      />,
    );
    expect(screen.getByText(/₦5,000 delivery masked at 10%/)).toBeInTheDocument();
  });
});
