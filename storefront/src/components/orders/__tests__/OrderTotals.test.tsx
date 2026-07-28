import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { OrderTotals } from "@/components/orders/OrderTotals";

const order = {
  currency: "GBP", subtotal: "50.00", discount_total: "0.00",
  shipping_total: "4.50", tax_total: "1.25", grand_total_display: "£55.75",
};

/** Pairs a row's <dt> with its own <dd>, so a swapped label and value fails. Asserting
 * the amounts alone would not: distinct rows can carry the same figure. */
function rowValue(label: string): string | undefined {
  const dt = screen.getByText(label);
  return dt.parentElement?.querySelector("dd")?.textContent ?? undefined;
}

describe("OrderTotals", () => {
  it("pairs every row with its own amount", () => {
    render(<OrderTotals order={{ ...order, discount_total: "5.00" }} />);

    expect(rowValue("Subtotal")).toBe("£50.00");
    expect(rowValue("Discount")).toBe("−£5.00");
    expect(rowValue("Delivery")).toBe("£4.50");
    expect(rowValue("Tax")).toBe("£1.25");
    // The grand total is the API's pre-formatted display string, not formatMoney output.
    expect(rowValue("Total")).toBe("£55.75");
  });

  it("hides the discount row when there is no discount", () => {
    render(<OrderTotals order={order} />);

    expect(screen.queryByText("Discount")).not.toBeInTheDocument();
    expect(rowValue("Subtotal")).toBe("£50.00");
    expect(rowValue("Delivery")).toBe("£4.50");
    expect(rowValue("Tax")).toBe("£1.25");
    expect(rowValue("Total")).toBe("£55.75");
  });

  it("uses the symbol for the order's own currency", () => {
    render(
      <OrderTotals
        order={{ ...order, currency: "NGN", subtotal: "20000.00", grand_total_display: "₦20,000.00" }}
      />,
    );

    expect(rowValue("Subtotal")).toBe("₦20,000.00");
  });
});
