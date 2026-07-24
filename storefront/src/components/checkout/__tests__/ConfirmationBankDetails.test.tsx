import { describe, it, expect, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { ConfirmationBankDetails } from "@/components/checkout/ConfirmationBankDetails";
import { stashBankHandoff } from "@/lib/bank-handoff";

describe("ConfirmationBankDetails", () => {
  afterEach(() => {
    sessionStorage.clear();
  });

  it("renders the stashed bank details for a matching order number", () => {
    stashBankHandoff("TC-1001", {
      display: { Bank: "GTB", "Account number": "0123456789" },
      reference: "TC-1001-REF",
    });

    render(<ConfirmationBankDetails number="TC-1001" amount="150.00" currency="GBP" />);

    expect(screen.getByText("Payment details")).toBeInTheDocument();
    expect(screen.getByText("0123456789")).toBeInTheDocument();
    expect(screen.getByText("TC-1001-REF")).toBeInTheDocument();
  });

  it("renders a muted fallback when nothing is stashed for this order number", () => {
    stashBankHandoff("TC-1001", { display: { Bank: "GTB" } });

    render(<ConfirmationBankDetails number="TC-9999" />);

    expect(
      screen.getByText(/Your bank transfer details were shown at checkout/i)
    ).toBeInTheDocument();
    expect(screen.queryByText("GTB")).not.toBeInTheDocument();
  });

  it("renders the muted fallback (no crash) when sessionStorage is empty", () => {
    render(<ConfirmationBankDetails number="TC-2002" />);

    expect(
      screen.getByText(/Contact support with your order number/i)
    ).toBeInTheDocument();
  });
});
