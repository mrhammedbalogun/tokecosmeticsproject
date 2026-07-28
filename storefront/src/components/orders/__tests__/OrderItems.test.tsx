import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { OrderItems } from "@/components/orders/OrderItems";
import type { OrderItem } from "@/lib/orders";

function item(overrides: Partial<OrderItem> = {}): OrderItem {
  return {
    product_name: "Glow Serum", variant_name: "Size: 150ml", sku: "GS-150",
    quantity: 2, unit_price: "25.00", line_total: "50.00",
    unit_price_display: "£25.00", line_total_display: "£50.00", image_url: null,
    ...overrides,
  };
}

describe("OrderItems", () => {
  it("renders the variant line when the item has one", () => {
    render(<OrderItems items={[item()]} />);

    expect(screen.getByText("Glow Serum")).toBeInTheDocument();
    // A pre-joined string, not a map — rendering it per-character was a real bug.
    expect(screen.getByText("Size: 150ml")).toBeInTheDocument();
    expect(screen.getByText("Qty 2")).toBeInTheDocument();
    expect(screen.getByText("£50.00")).toBeInTheDocument();
  });

  it("omits the variant line when variant_name is empty", () => {
    const { container } = render(<OrderItems items={[item({ variant_name: "" })]} />);

    expect(screen.getByText("Glow Serum")).toBeInTheDocument();
    expect(container.querySelectorAll("p.text-muted")).toHaveLength(1); // Qty only
  });

  it("renders one row per item", () => {
    render(
      <OrderItems
        items={[item(), item({ product_name: "Body Butter", line_total_display: "£12.00" })]}
      />,
    );

    expect(screen.getByText("Glow Serum")).toBeInTheDocument();
    expect(screen.getByText("Body Butter")).toBeInTheDocument();
  });
});
