import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { AddressSummary } from "@/components/orders/AddressBlock";

describe("AddressSummary", () => {
  it("renders every line of a full snapshot", () => {
    render(
      <AddressSummary
        address={{
          first_name: "Ada", last_name: "Lovelace", line1: "12 Analytical Way",
          line2: "Flat 3", city_text: "London", state_text: "Greater London",
          postcode: "EC1A 1AA", phone: "+44 7700 900123",
        }}
      />,
    );

    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.getByText("12 Analytical Way")).toBeInTheDocument();
    expect(screen.getByText("Flat 3")).toBeInTheDocument();
    expect(screen.getByText("London, Greater London")).toBeInTheDocument();
    expect(screen.getByText("EC1A 1AA")).toBeInTheDocument();
    expect(screen.getByText("+44 7700 900123")).toBeInTheDocument();
  });

  it("skips the keys a partial snapshot is missing", () => {
    const { container } = render(
      <AddressSummary address={{ first_name: "Ada", line1: "12 Analytical Way" }} />,
    );

    expect(screen.getByText("Ada")).toBeInTheDocument();
    expect(container.querySelectorAll("span.block")).toHaveLength(2);
  });

  it("falls back when the address is null", () => {
    render(<AddressSummary address={null} />);

    expect(screen.getByText("No address on file.")).toBeInTheDocument();
  });

  it("skips non-string junk values rather than crashing", () => {
    render(
      <AddressSummary
        address={{
          first_name: "Ada", last_name: 42, line1: { nested: true },
          line2: null, city_text: ["London"], postcode: "   ",
        }}
      />,
    );

    expect(screen.getByText("Ada")).toBeInTheDocument();
    expect(screen.queryByText("42")).not.toBeInTheDocument();
  });

  it("falls back when the snapshot has no usable string values at all", () => {
    render(<AddressSummary address={{ first_name: 1, line1: null, postcode: "  " }} />);

    expect(screen.getByText("No address on file.")).toBeInTheDocument();
  });
});
