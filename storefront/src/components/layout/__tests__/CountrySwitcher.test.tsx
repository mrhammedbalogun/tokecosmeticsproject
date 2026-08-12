import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { CountrySwitcher } from "@/components/layout/CountrySwitcher";
import type { Market } from "@/lib/country";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));

const markets: Market[] = [
  { code: "NG", name: "Nigeria", currency: { code: "NGN", symbol: "₦", decimal_places: 2 }, is_default: true, is_rest_of_world: false, area_label: "LGA" },
  { code: "CA", name: "Canada", currency: { code: "CAD", symbol: "CA$", decimal_places: 2 }, is_default: false, is_rest_of_world: false, area_label: "Municipality" },
];

describe("CountrySwitcher", () => {
  it("shows the current market", () => {
    render(<CountrySwitcher markets={markets} current="CA" />);
    expect(screen.getByRole("combobox")).toHaveValue("CA");
  });

  it("follows a country change made elsewhere (welcome popup) on refresh re-render", () => {
    // The bug: useState(current) froze the mount value, so after the popup switched the
    // cookie and router.refresh()ed, prices updated but this select stayed on the old
    // market until a hard reload. The re-render with a new `current` must win.
    const { rerender } = render(<CountrySwitcher markets={markets} current="CA" />);
    rerender(<CountrySwitcher markets={markets} current="NG" />);
    expect(screen.getByRole("combobox")).toHaveValue("NG");
  });
});
