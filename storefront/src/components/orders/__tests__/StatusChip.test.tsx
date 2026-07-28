import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatusChip } from "@/components/orders/StatusChip";

describe("StatusChip", () => {
  it.each([
    ["pending_payment", "Awaiting payment"],
    ["processing", "Processing"],
    ["shipped", "Shipped"],
    ["delivered", "Delivered"],
    ["completed", "Completed"],
    ["cancelled", "Cancelled"],
    ["expired", "Expired"],
    ["refunded", "Refunded"],
    ["on_hold", "On hold"],
  ])("renders %s as %s — never the raw slug", (status, label) => {
    render(<StatusChip status={status} />);

    expect(screen.getByText(label)).toBeInTheDocument();
    expect(screen.queryByText(status)).not.toBeInTheDocument();
  });

  it("falls back to the raw value for an unknown status", () => {
    // The backend status field has no choices constraint, so a new slug must show up
    // as-is rather than crash or silently disappear from the customer's history.
    render(<StatusChip status="awaiting_pickup" />);

    expect(screen.getByText("awaiting_pickup")).toBeInTheDocument();
  });

  it("gives an unknown status the neutral tone", () => {
    const { container } = render(<StatusChip status="awaiting_pickup" />);

    expect(container.firstElementChild).toHaveClass("bg-beige", "text-muted");
  });

  it("tones delivered and cancelled differently", () => {
    const { container: good } = render(<StatusChip status="delivered" />);
    const { container: dead } = render(<StatusChip status="cancelled" />);

    expect(good.firstElementChild?.className).not.toEqual(dead.firstElementChild?.className);
  });
});
