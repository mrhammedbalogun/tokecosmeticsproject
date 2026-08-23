import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AajPanel, type AajPanelData } from "@/components/order/AajPanel";
import type { WriteState } from "@/app/(shell)/orders/[number]/actions";

const DESK = ["orders.view", "orders.operate", "orders.manage"];

function data(over: Partial<AajPanelData> = {}, ship: Partial<AajPanelData["shipment"]> = {}): AajPanelData {
  return {
    shipment: {
      status: "quoted",
      booking_id: "",
      tracking_id: "",
      quote_total: "2779.00",
      cost: null,
      charged: "2779.00",
      eta_days: 2,
      label_url: "",
      last_scan: {},
      last_status: null,
      last_tracked_at: null,
      origin: { id: 1, name: "Ogudu Mall (Lagos)", address: "Shop 1, Ogudu Mall", state_name: "Lagos" },
      ...ship,
    },
    can_capture: true,
    capture_blocked_reason: "",
    can_check: false,
    can_void: false,
    void_blocked_reason: "",
    process_enabled: true,
    ...over,
  };
}

type Action = (i: { number: string }) => Promise<WriteState>;

function setup(d: AajPanelData = data(), scopes: string[] = DESK) {
  const capture = vi.fn<Action>(async () => ({ success: "AAJ shipment D276AA3D created — ₦2392.00 charged to the AAJ account (booking bk-1). Print the label and hand the parcel to AAJ." }));
  const check = vi.fn<Action>(async () => ({ success: "AAJ confirms the charge went through — the shipment is created.", code: "check_created" }));
  const voidFn = vi.fn<Action>(async () => ({ success: "AAJ shipment D276AA3D voided — the charge is reversed. Create the shipment again to rebook." }));
  const label = vi.fn<Action>(async () => ({ error: "AAJ has not issued the label yet.", code: "label_not_ready" }));
  render(<AajPanel number="TC-100001" data={d} scopes={scopes} actions={{ capture, check, void: voidFn, label }} />);
  return { capture, check, voidFn, label };
}

describe("AajPanel", () => {
  it("capture is a two-step act that names the charge and the packing shop, then reports the tracking id", async () => {
    const { capture } = setup();
    fireEvent.click(screen.getByRole("button", { name: /create aaj shipment/i }));
    expect(capture).not.toHaveBeenCalled();
    expect(screen.getByText(/then charges/i)).toBeInTheDocument();
    expect(screen.getAllByText(/₦2779\.00/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Ogudu Mall \(Lagos\)/, { selector: "span" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^create shipment$/i }));
    await waitFor(() => expect(capture).toHaveBeenCalledWith({ number: "TC-100001" }));
    expect(await screen.findByRole("status")).toHaveTextContent(/D276AA3D created/i);
  });

  it("shows retail quote beside the booked cost, and the kill-switch notice when charging is off", () => {
    setup(data({ process_enabled: false }, { status: "booked", booking_id: "bk-1", cost: "2392.00" }));
    expect(screen.getByText(/AAJ charges us/i)).toBeInTheDocument();
    expect(screen.getByText(/retail quote was ₦2779\.00/i)).toBeInTheDocument();
    expect(screen.getByText(/Charging is switched off/i)).toBeInTheDocument();
    // From `booked`, the button re-runs only the charge — never a second booking.
    expect(screen.getByRole("button", { name: /charge aaj booking/i })).toBeInTheDocument();
  });

  it("greys capture without orders.manage and when the backend says no", () => {
    setup(data(), ["orders.view", "orders.operate"]);
    expect(screen.getByRole("button", { name: /create aaj shipment/i })).toBeDisabled();
    document.body.innerHTML = "";
    setup(data({ can_capture: false, capture_blocked_reason: "order is pending_payment — capture after payment" }));
    expect(screen.getByRole("button", { name: /create aaj shipment/i })).toBeDisabled();
    expect(screen.getByText(/capture after payment/i)).toBeInTheDocument();
  });

  it("create_unconfirmed forbids a blind retry but offers the read-only check", async () => {
    const { check, capture } = setup(data({ can_check: true }, { status: "create_unconfirmed", booking_id: "bk-9" }));
    expect(screen.getByText(/Never\s+create again blind/i)).toBeInTheDocument();
    expect(screen.getAllByText("bk-9").length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: /create aaj shipment/i })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /check with aaj/i }));
    await waitFor(() => expect(check).toHaveBeenCalledWith({ number: "TC-100001" }));
    expect(await screen.findByRole("status")).toHaveTextContent(/charge went through/i);
    expect(capture).not.toHaveBeenCalled();
  });

  it("void is confirmed, named by tracking id, and greyed past the first hub scan", async () => {
    const { voidFn } = setup(data({ can_void: true }, { status: "created", tracking_id: "D276AA3D", booking_id: "bk-1", cost: "2392.00", label_url: "https://aaj.test/l.pdf" }));
    expect(screen.getByRole("link", { name: /open label pdf/i })).toHaveAttribute("href", "https://aaj.test/l.pdf");
    fireEvent.click(screen.getByRole("button", { name: /void shipment/i }));
    expect(voidFn).not.toHaveBeenCalled();
    expect(screen.getByText(/Void D276AA3D and reverse ₦2392\.00/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^void$/i }));
    await waitFor(() => expect(voidFn).toHaveBeenCalledWith({ number: "TC-100001" }));
    expect(await screen.findByRole("status")).toHaveTextContent(/charge is reversed/i);

    document.body.innerHTML = "";
    setup(data({ can_void: false, void_blocked_reason: "AAJ has already scanned it (ORIGIN_SCAN)" }, { status: "in_transit", tracking_id: "D276AA3D", last_scan: { scanType: "ORIGIN_SCAN", description: "Received at yaba", dateTime: "2026-08-23T16:06:38.000000+01:00" } }));
    expect(screen.getByRole("button", { name: /void shipment/i })).toBeDisabled();
    expect(screen.getByText(/Received at yaba/)).toBeInTheDocument();
  });

  it("a voided shipment offers a rebook; label fetch reports not-ready as a sentence", async () => {
    const { label } = setup(data({}, { status: "voided", booking_id: "bk-1" }));
    expect(screen.getByRole("button", { name: /rebook with aaj/i })).toBeInTheDocument();
    document.body.innerHTML = "";
    const s = setup(data({}, { status: "created", tracking_id: "D276AA3D" }));
    fireEvent.click(screen.getByRole("button", { name: /fetch label/i }));
    await waitFor(() => expect(s.label).toHaveBeenCalledWith({ number: "TC-100001" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/not issued the label yet/i);
    expect(label).not.toHaveBeenCalled();
  });
});
