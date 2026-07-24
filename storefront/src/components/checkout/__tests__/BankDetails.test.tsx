import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { BankDetails } from "@/components/checkout/BankDetails";

describe("BankDetails", () => {
  it("renders the display map as label/value rows, plus reference and instructions", () => {
    render(
      <BankDetails
        data={{
          display: { Bank: "GTB", "Account number": "0123456789" },
          reference: "TC-1",
          instructions: "Use your order number.",
        }}
      />
    );
    expect(screen.getByText("Bank")).toBeInTheDocument();
    expect(screen.getByText("GTB")).toBeInTheDocument();
    expect(screen.getByText("Account number")).toBeInTheDocument();
    expect(screen.getByText("0123456789")).toBeInTheDocument();
    expect(screen.getByText("TC-1")).toBeInTheDocument();
    expect(screen.getByText("Use your order number.")).toBeInTheDocument();
  });

  it("falls back to bank_name/account_name/account_number when display is absent", () => {
    render(
      <BankDetails
        data={{
          bank_name: "Zenith Bank",
          account_name: "Toke Cosmetics Ltd",
          account_number: "9988776655",
        }}
      />
    );
    expect(screen.getByText("Bank")).toBeInTheDocument();
    expect(screen.getByText("Zenith Bank")).toBeInTheDocument();
    expect(screen.getByText("Account name")).toBeInTheDocument();
    expect(screen.getByText("Toke Cosmetics Ltd")).toBeInTheDocument();
    expect(screen.getByText("Account number")).toBeInTheDocument();
    expect(screen.getByText("9988776655")).toBeInTheDocument();
  });

  it("shows the amount to transfer when amount + currency are given", () => {
    render(<BankDetails data={{ display: { Bank: "GTB" } }} amount="150.00" currency="GBP" />);
    expect(screen.getByText("£150.00")).toBeInTheDocument();
  });
});
