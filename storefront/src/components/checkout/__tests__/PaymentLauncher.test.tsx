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

// The switcher owns its own fetching; stub it and expose buttons that fire each callback.
vi.mock("@/components/checkout/PaymentMethodSwitch", () => ({
  PaymentMethodSwitch: ({
    currentGateway,
    onRelaunch,
    onBankDetails,
  }: {
    currentGateway: string;
    onRelaunch: (l: { gateway: string; reference: string; orderNumber: string; data: Record<string, unknown> }) => void;
    onBankDetails: (n: string, d: Record<string, unknown>) => void;
  }) => (
    <div>
      <span>switch-for:{currentGateway}</span>
      <button
        onClick={() =>
          onRelaunch({ gateway: "flutterwave", reference: "FLW-9", orderNumber: "TC-200", data: {} })
        }
      >
        pick-flutterwave
      </button>
      <button onClick={() => onBankDetails("TC-200", { display: { Bank: "GTB" } })}>pick-bank</button>
    </div>
  ),
}));

const stashBankHandoff = vi.fn();
vi.mock("@/lib/bank-handoff", () => ({
  stashBankHandoff: (n: string, d: Record<string, unknown>) => stashBankHandoff(n, d),
}));

import { PaymentLauncher } from "@/components/checkout/PaymentLauncher";

beforeEach(() => {
  replace.mockClear();
  verifyPayment.mockReset();
  stashBankHandoff.mockClear();
  capturedSuccess = null;
});

const launch = (gateway: string) => ({
  gateway,
  reference: "TC-ref-1",
  orderNumber: "TC-200",
  data: {},
});

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

  it("names the saved order on the failure screen so the customer knows it exists", async () => {
    render(<PaymentLauncher launch={launch("paystack")} />);
    fireEvent.click(screen.getByText("ps-abort"));
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByText(/TC-200/)).toBeInTheDocument();
  });

  it("retries into the same gateway launch after an abort", async () => {
    // The order is already placed and the cart converted, so there is nowhere to go back
    // to: retry must re-open THIS launch. The access code / PayPal order id is still
    // valid, which is exactly what resuming an abandoned transaction is for.
    verifyPayment.mockResolvedValue({
      ok: true,
      orderNumber: "TC-200",
      paymentStatus: "succeeded",
      orderStatus: "processing",
    });
    render(<PaymentLauncher launch={launch("paystack")} />);
    fireEvent.click(screen.getByText("ps-abort"));
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /try again/i }));

    // Back to collecting: the child is mounted again and can still complete the payment.
    await waitFor(() => expect(screen.getByText("ps-ok")).toBeInTheDocument());
    fireEvent.click(screen.getByText("ps-ok"));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/checkout/confirmation/TC-200"));
  });

  it("offers a method switch after an abort, keyed to the gateway that failed", async () => {
    render(<PaymentLauncher launch={launch("paystack")} />);
    fireEvent.click(screen.getByText("ps-abort"));
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /choose another/i }));
    await waitFor(() => expect(screen.getByText("switch-for:paystack")).toBeInTheDocument());
  });

  it("collects on the newly chosen gateway after a switch", async () => {
    verifyPayment.mockResolvedValue({
      ok: true,
      orderNumber: "TC-200",
      paymentStatus: "succeeded",
      orderStatus: "processing",
    });
    render(<PaymentLauncher launch={launch("paystack")} />);
    fireEvent.click(screen.getByText("ps-abort"));
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /choose another/i }));
    await waitFor(() => expect(screen.getByText("pick-flutterwave")).toBeInTheDocument());

    fireEvent.click(screen.getByText("pick-flutterwave"));

    // The launcher swaps to the new gateway's child rather than reopening the old one.
    await waitFor(() => expect(screen.getByText("flutterwave-child")).toBeInTheDocument());
  });

  it("stashes bank details and routes to confirmation when the switch lands on bank transfer", async () => {
    render(<PaymentLauncher launch={launch("paystack")} />);
    fireEvent.click(screen.getByText("ps-abort"));
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /choose another/i }));
    await waitFor(() => expect(screen.getByText("pick-bank")).toBeInTheDocument());

    fireEvent.click(screen.getByText("pick-bank"));

    await waitFor(() =>
      expect(stashBankHandoff).toHaveBeenCalledWith("TC-200", { display: { Bank: "GTB" } })
    );
    expect(replace).toHaveBeenCalledWith("/checkout/confirmation/TC-200");
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
