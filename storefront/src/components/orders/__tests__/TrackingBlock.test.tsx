import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { TrackingBlock } from "@/components/orders/TrackingBlock";

const order = (o: Partial<Parameters<typeof TrackingBlock>[0]["order"]> = {}) => ({
  status: "pending_payment", tracking_carrier: "", tracking_number: "", ...o,
});

describe("TrackingBlock", () => {
  it("joins carrier and number with a separator", () => {
    render(<TrackingBlock order={order({ status: "shipped", tracking_carrier: "GIG", tracking_number: "GX9911" })} />);

    expect(screen.getByRole("heading", { name: "Tracking" })).toBeInTheDocument();
    expect(screen.getByText("GIG · GX9911")).toBeInTheDocument();
  });

  it.each([
    ["carrier only", { tracking_carrier: "GIG", tracking_number: "" }, "GIG"],
    ["number only", { tracking_carrier: "", tracking_number: "GX9911" }, "GX9911"],
    ["whitespace half", { tracking_carrier: "   ", tracking_number: "GX9911" }, "GX9911"],
  ])("renders %s with no dangling separator", (_label, fields, expected) => {
    render(<TrackingBlock order={order({ status: "shipped", ...fields })} />);

    expect(screen.getByText(expected)).toBeInTheDocument();
  });

  // PRE_SHIP membership IS the decision, so both directions are pinned per status rather
  // than by one representative each — dropping a member has to fail a test.
  it.each([["pending_payment"], ["processing"]])(
    "shows the pre-ship hint for a %s order with no tracking",
    (status) => {
      render(<TrackingBlock order={order({ status })} />);

      expect(screen.getByText(/tracking details when your order ships/i)).toBeInTheDocument();
    },
  );

  it.each([["cancelled"], ["expired"], ["refunded"], ["delivered"], ["completed"], ["shipped"], ["on_hold"]])(
    "renders nothing at all for a %s order with no tracking",
    (status) => {
      // The hint promises a shipment. on_hold in particular is the triage state for the
      // Plan-14a freight-declined cohort — customers we owe a REFUND.
      const { container } = render(<TrackingBlock order={order({ status })} />);

      expect(container).toBeEmptyDOMElement();
    },
  );

  it("still shows real tracking on an on_hold order that has some", () => {
    // Omitting the hint must not omit facts: an order held after shipping still has a
    // consignment the customer can chase.
    render(<TrackingBlock order={order({ status: "on_hold", tracking_carrier: "GIG", tracking_number: "GX9911" })} />);

    expect(screen.getByText("GIG · GX9911")).toBeInTheDocument();
  });
});
