import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { OrderTotals } from "@/components/orders/OrderTotals";

const order = {
  currency: "GBP", subtotal: "50.00", discount_total: "0.00",
  shipping_total: "4.50", tax_total: "0.00", grand_total_display: "£54.50",
};

describe("OrderTotals", () => {
  it("renders every money row with the currency symbol", () => {
    render(<OrderTotals order={order} />);

    expect(screen.getByText("£50.00")).toBeInTheDocument();
    expect(screen.getByText("£4.50")).toBeInTheDocument();
    expect(screen.getByText("£54.50")).toBeInTheDocument();
  });

  it("hides the discount row when there is no discount", () => {
    render(<OrderTotals order={order} />);

    expect(screen.queryByText("Discount")).not.toBeInTheDocument();
  });

  it("shows a negated discount row when discount_total is non-zero", () => {
    render(<OrderTotals order={{ ...order, discount_total: "5.00" }} />);

    expect(screen.getByText("Discount")).toBeInTheDocument();
    expect(screen.getByText("−£5.00")).toBeInTheDocument();
  });
});
