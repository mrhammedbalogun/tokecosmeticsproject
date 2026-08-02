import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { GigPanel, type GigPanelData } from "@/components/order/GigPanel";
import type { WriteState } from "@/app/(shell)/orders/[number]/actions";

const DESK = ["orders.view", "orders.operate", "orders.manage"];

function data(over: Partial<GigPanelData> = {}, ship: Partial<GigPanelData["shipment"]> = {}): GigPanelData {
  return {
    shipment: {
      status: "quoted",
      waybill: "",
      cost: null,
      charged: "4175.20",
      quote: { price: "4175.20", breakdown: { GrandTotal: 4175.2 } },
      label_url: "",
      capture_api_id: "",
      last_scan: {},
      last_tracked_at: null,
      ...ship,
    },
    wallet_balance: "50000",
    can_capture: true,
    capture_blocked_reason: "",
    ...over,
  };
}

function setup(
  d: GigPanelData = data(),
  scopes: string[] = DESK,
  capture = vi.fn<(i: { number: string }) => Promise<WriteState>>(async () => ({
    success: "Waybill 1349113095 created — ₦4175.20 debited from the GIG wallet. A rider has been dispatched.",
  })),
  label = vi.fn<(i: { number: string }) => Promise<WriteState>>(async () => ({
    error: "Label not generated yet", code: "label_not_ready",
  })),
) {
  render(<GigPanel number="TC-100001" data={d} scopes={scopes} actions={{ capture, label }} />);
  return { capture, label };
}

describe("GigPanel", () => {
  it("capture is a two-step act that names the money, then reports the waybill", async () => {
    const { capture } = setup();
    // Step 1: the button opens a confirm that names the amount — nothing is sent yet.
    fireEvent.click(screen.getByRole("button", { name: /create gig waybill/i }));
    expect(capture).not.toHaveBeenCalled();
    expect(screen.getByText(/debits/i)).toBeInTheDocument();
    expect(screen.getAllByText(/₦4175\.20/).length).toBeGreaterThan(0);
    expect(screen.getByText(/cannot be cancelled/i)).toBeInTheDocument();
    // Step 2: the confirm actually captures.
    fireEvent.click(screen.getByRole("button", { name: /^create waybill$/i }));
    await waitFor(() => expect(capture).toHaveBeenCalledWith({ number: "TC-100001" }));
    expect(await screen.findByRole("status")).toHaveTextContent(/rider has been dispatched/i);
  });

  it("greys capture without orders.manage and when the backend says no", () => {
    setup(data(), ["orders.view", "orders.operate"]);
    expect(screen.getByRole("button", { name: /create gig waybill/i })).toBeDisabled();

    document.body.innerHTML = "";
    setup(data({ can_capture: false, capture_blocked_reason: "order is pending_payment — capture after payment" }));
    expect(screen.getByRole("button", { name: /create gig waybill/i })).toBeDisabled();
    expect(screen.getByText(/capture after payment/i)).toBeInTheDocument();
  });

  it("renders create_unconfirmed as a forbid-retry warning with no capture button", () => {
    setup(data({}, { status: "create_unconfirmed", capture_api_id: "api-123" }));
    expect(screen.getByText(/check with gig before anything else/i)).toBeInTheDocument();
    expect(screen.getByText(/pay twice and dispatch two riders/i)).toBeInTheDocument();
    expect(screen.getByText("api-123")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /create gig waybill/i })).not.toBeInTheDocument();
  });

  it("label: not-ready is a sentence with a retry, a URL becomes a link, no waybill no button", async () => {
    const { label } = setup(data({}, { status: "created", waybill: "1349113095" }));
    fireEvent.click(screen.getByRole("button", { name: /fetch label/i }));
    await waitFor(() => expect(label).toHaveBeenCalledWith({ number: "TC-100001" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/not generated yet/i);
    // Still a button — not-ready is retryable, unlike capture.
    expect(screen.getByRole("button", { name: /fetch label/i })).toBeInTheDocument();

    document.body.innerHTML = "";
    setup(data({}, { status: "created", waybill: "1349113095", label_url: "https://s3.example/l.pdf" }));
    expect(screen.getByRole("link", { name: /open label pdf/i })).toHaveAttribute(
      "href", "https://s3.example/l.pdf",
    );

    document.body.innerHTML = "";
    setup(data());  // quoted: no waybill yet
    expect(screen.queryByRole("button", { name: /fetch label/i })).not.toBeInTheDocument();
  });

  it("an unknown wallet balance says unknown, never zero, and the raw scan renders verbatim", () => {
    setup(data({ wallet_balance: null }, {
      status: "in_transit", waybill: "1349113095",
      last_scan: { Status: "MAHD", Location: "GBAGADA" }, last_tracked_at: "2026-08-02T18:00:00Z",
    }));
    expect(screen.getByText("unknown")).toBeInTheDocument();
    expect(screen.queryByText(/₦0/)).not.toBeInTheDocument();
    expect(screen.getByText(/MAHD/)).toBeInTheDocument();
  });
});
