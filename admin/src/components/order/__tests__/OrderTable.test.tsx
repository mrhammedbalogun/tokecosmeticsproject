import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { OrderTable } from "@/components/order/OrderTable";
import { OrderStatusTabs } from "@/components/order/OrderStatusTabs";
import type { OrderRow } from "@/lib/orders";

const row = (over: Partial<OrderRow> = {}): OrderRow => ({
  number: "TC-100001",
  status: "processing",
  review_reason: "",
  placed_at: "2026-07-30T10:00:00Z",
  email: "buyer@example.test",
  country: "NG",
  currency: "NGN",
  grand_total: "2000.00",
  grand_total_display: "₦2,000.00",
  source: "web",
  ...over,
});

describe("OrderTable", () => {
  it("links each order to its detail page", () => {
    render(<OrderTable rows={[row()]} />);

    expect(screen.getByRole("link", { name: "TC-100001" })).toHaveAttribute(
      "href",
      "/orders/TC-100001",
    );
  });

  it("shows the customer and the total", () => {
    render(<OrderTable rows={[row()]} />);

    expect(screen.getByText("buyer@example.test")).toBeInTheDocument();
    expect(screen.getByText("₦2,000.00")).toBeInTheDocument();
  });

  it("SHOWS THE FLAG ON THE ROW, not only behind the needs-attention filter", () => {
    // Every review_reason is a money discrepancy and four of five say "refund". An
    // operator scanning the queue should see which orders are wrong without first knowing
    // to go looking.
    render(
      <OrderTable
        rows={[row({ review_reason: "overpaid by ₦500.00 NGN — refund the difference" })]}
      />,
    );

    expect(
      screen.getByText("overpaid by ₦500.00 NGN — refund the difference"),
    ).toBeInTheDocument();
  });

  it("lists accumulated reasons separately", () => {
    // Newline-separated since the backend separator fix, so a reason containing a
    // semicolon stays whole. See lib/orders.ts.
    const both =
      "overpaid by 500.00 NGN — refund the difference\n" +
      "possible double payment — order already processing; refund payment 7";
    render(<OrderTable rows={[row({ review_reason: both })]} />);

    expect(screen.getByText("overpaid by 500.00 NGN — refund the difference")).toBeInTheDocument();
    expect(
      screen.getByText("possible double payment — order already processing; refund payment 7"),
    ).toBeInTheDocument();
  });

  it("renders the date without applying the server's locale", () => {
    // This renders on the server, so toLocaleDateString would present the SERVER's locale
    // as the reader's — which is how 03/04 becomes ambiguous.
    render(<OrderTable rows={[row()]} />);

    expect(screen.getByText("2026-07-30")).toBeInTheDocument();
  });

  it("copes with a legacy order that has no placed_at", () => {
    render(<OrderTable rows={[row({ placed_at: null })]} />);

    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("marks a non-web order with its source", () => {
    // Plan-23 migrates 879 legacy orders; knowing one came from WooCommerce matters when
    // its shape looks odd.
    render(<OrderTable rows={[row({ source: "woocommerce_ng" })]} />);

    expect(screen.getByText("woocommerce_ng")).toBeInTheDocument();
  });

  it("says so when nothing matched rather than rendering an empty table", () => {
    render(<OrderTable rows={[]} />);

    expect(screen.getByText("No orders match those filters.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});

describe("OrderStatusTabs", () => {
  it("marks All as current when nothing is filtered", () => {
    render(<OrderStatusTabs filters={{ page: 1 }} />);

    expect(screen.getByRole("link", { name: "All" })).toHaveAttribute("aria-current", "page");
  });

  it("links a status without carrying needs_attention along", () => {
    render(<OrderStatusTabs filters={{ needs_attention: true, page: 1 }} />);

    expect(screen.getByRole("link", { name: "Processing" })).toHaveAttribute(
      "href",
      "/orders?status=processing",
    );
  });

  it("KEEPS NEEDS ATTENTION SEPARATE FROM THE STATUSES", () => {
    // review_reason is orthogonal to the lifecycle — there is no needs_review status.
    // Listing it among them would teach an operator a category the system lacks.
    render(<OrderStatusTabs filters={{ page: 1 }} />);

    const nav = screen.getByRole("navigation");
    expect(within(nav).getByRole("link", { name: "Needs attention" })).toHaveAttribute(
      "href",
      "/orders?needs_attention=true",
    );
  });

  it("RESETS TO PAGE 1 when the queue changes", () => {
    // Keeping page 7 while narrowing is how somebody lands on an empty page and concludes
    // the filter matched nothing.
    render(<OrderStatusTabs filters={{ page: 7 }} />);

    expect(screen.getByRole("link", { name: "Shipped" })).toHaveAttribute(
      "href",
      "/orders?status=shipped",
    );
  });

  it("preserves the other filters when switching status", () => {
    render(<OrderStatusTabs filters={{ search: "jane", country: "NG", page: 1 }} />);

    const href = screen.getByRole("link", { name: "Shipped" }).getAttribute("href")!;
    expect(href).toContain("search=jane");
    expect(href).toContain("country=NG");
    expect(href).toContain("status=shipped");
  });

  it("offers every status the state machine has", () => {
    render(<OrderStatusTabs filters={{ page: 1 }} />);

    for (const label of ["Pending payment", "On hold", "Refunded", "Expired"]) {
      expect(screen.getByRole("link", { name: label })).toBeInTheDocument();
    }
  });
});
