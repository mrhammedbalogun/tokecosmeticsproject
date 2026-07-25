import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));

const verifyPayment = vi.fn();
vi.mock("@/lib/payment-verify", () => ({ verifyPayment: (r: string) => verifyPayment(r) }));

// Child stubs: each exposes a button to fire the gateway success/abort callbacks. The
// success callback is also captured so a test can invoke it directly (see the
// fires-twice-in-one-tick case, where the button is already unmounted).
let capturedSuccess: (() => void) | null = null;
vi.mock("@/components/checkout/PaystackLaunch", () => ({
  PaystackLaunch: ({
    onGatewaySuccess,
    onGatewayAbort,
  }: {
    onGatewaySuccess: () => void;
    onGatewayAbort: () => void;
  }) => {
    capturedSuccess = onGatewaySuccess;
    return (
      <div>
        <button onClick={onGatewaySuccess}>ps-ok</button>
        <button onClick={onGatewayAbort}>ps-abort</button>
      </div>
    );
  },
}));
vi.mock("@/components/checkout/PaypalLaunch", () => ({
  PaypalLaunch: () => <div>paypal-child</div>,
}));
vi.mock("@/components/checkout/FlutterwaveLaunch", () => ({
  FlutterwaveLaunch: () => <div>flutterwave-child</div>,
}));

import { PaymentLauncher } from "@/components/checkout/PaymentLauncher";

beforeEach(() => {
  replace.mockClear();
  verifyPayment.mockReset();
  capturedSuccess = null;
});

const launch = (gateway: string) => ({ gateway, reference: "TC-ref-1", data: {} });

describe("PaymentLauncher", () => {
  it("routes to confirmation when a Paystack success verifies as succeeded", async () => {
    verifyPayment.mockResolvedValue({
      ok: true,
      orderNumber: "TC-77",
      paymentStatus: "succeeded",
      orderStatus: "processing",
    });
    render(<PaymentLauncher launch={launch("paystack")} />);
    fireEvent.click(screen.getByText("ps-ok"));
    await waitFor(() => expect(verifyPayment).toHaveBeenCalledWith("TC-ref-1"));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/checkout/confirmation/TC-77"));
  });

  it("shows a retry state (no navigation) when the buyer aborts", async () => {
    render(<PaymentLauncher launch={launch("paystack")} />);
    fireEvent.click(screen.getByText("ps-abort"));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/didn.t go through|not completed/i)
    );
    expect(replace).not.toHaveBeenCalled();
    expect(verifyPayment).not.toHaveBeenCalled();
  });

  it("shows a calm pending state when verify is not yet succeeded", async () => {
    verifyPayment.mockResolvedValue({
      ok: true,
      orderNumber: "TC-77",
      paymentStatus: "pending",
      orderStatus: "pending_payment",
    });
    render(<PaymentLauncher launch={launch("paystack")} />);
    fireEvent.click(screen.getByText("ps-ok"));
    await waitFor(() =>
      expect(screen.getByText(/confirming your payment/i)).toBeInTheDocument()
    );
    expect(replace).not.toHaveBeenCalled();
  });

  it("shows the pending state (never a dead spinner) when verify itself fails", async () => {
    verifyPayment.mockResolvedValue({
      ok: false,
      orderNumber: null,
      paymentStatus: null,
      orderStatus: null,
    });
    render(<PaymentLauncher launch={launch("paystack")} />);
    fireEvent.click(screen.getByText("ps-ok"));
    await waitFor(() =>
      expect(screen.getByText(/confirming your payment/i)).toBeInTheDocument()
    );
    expect(replace).not.toHaveBeenCalled();
  });

  it("verifies only once when the SDK fires its success callback twice in one tick", async () => {
    // The phase change already unmounts the child after one click, so drive the callback
    // directly — an SDK that calls back twice before React re-renders must not start two
    // verifies (and two navigations).
    verifyPayment.mockResolvedValue({
      ok: true,
      orderNumber: "TC-77",
      paymentStatus: "succeeded",
      orderStatus: "processing",
    });
    render(<PaymentLauncher launch={launch("paystack")} />);
    const fire = capturedSuccess;
    expect(fire).toBeTypeOf("function");
    await act(async () => {
      void fire!();
      void fire!();
    });
    await waitFor(() => expect(replace).toHaveBeenCalledTimes(1));
    expect(verifyPayment).toHaveBeenCalledTimes(1);
  });

  it("renders the PayPal child for a paypal launch", () => {
    render(<PaymentLauncher launch={launch("paypal")} />);
    expect(screen.getByText("paypal-child")).toBeInTheDocument();
  });

  it("renders the Flutterwave child for a flutterwave launch", () => {
    render(<PaymentLauncher launch={launch("flutterwave")} />);
    expect(screen.getByText("flutterwave-child")).toBeInTheDocument();
  });

  it("shows an alert for an unknown gateway instead of a blank step", () => {
    render(<PaymentLauncher launch={launch("dogecoin")} />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });
});
