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

describe("the free gift", () => {
  const line = (over: Partial<OrderItem> = {}): OrderItem => ({
    product_name: "Shea Butter", variant_name: "400ml", sku: "SKU-1", quantity: 1,
    unit_price: "1000.00", line_total: "1000.00",
    unit_price_display: "₦1,000.00", line_total_display: "₦1,000.00",
    image_url: null, ...over,
  });

  it("names it once, however many lines the bundle had", () => {
    // The snapshot repeats on every line of the same bundle — a four-product box carries
    // it four times, and the customer is owed one sachet.
    render(
      <OrderItems
        items={[
          line({ sku: "A", combo_gift: "Free Kids Hair Grow Cream" }),
          line({ sku: "B", combo_gift: "Free Kids Hair Grow Cream" }),
        ]}
      />,
    );
    expect(screen.getAllByText("Free Kids Hair Grow Cream")).toHaveLength(1);
  });

  it("says nothing for an order that was promised nothing", () => {
    render(<OrderItems items={[line()]} />);
    expect(screen.queryByText(/free gift/i)).toBeNull();
  });
});
