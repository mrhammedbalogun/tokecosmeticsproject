import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

// Mock the React PayPal SDK: the provider records the options it was loaded with (the
// currency matters — see the currency test) and passes children through; Buttons renders
// two buttons wired to onApprove / onCancel so we can drive both paths deterministically.
const providerOptions: Record<string, unknown>[] = [];
vi.mock("@paypal/react-paypal-js", () => ({
  PayPalScriptProvider: ({
    children,
    options,
  }: {
    children: React.ReactNode;
    options: Record<string, unknown>;
  }) => {
    providerOptions.push(options);
    return <>{children}</>;
  },
  PayPalButtons: ({
    onApprove,
    onCancel,
    createOrder,
  }: {
    onApprove: (d: unknown, a: unknown) => void;
    onCancel: () => void;
    createOrder: (d: unknown, a: unknown) => Promise<string>;
  }) => (
    <div>
      <button onClick={() => onApprove({}, {})}>pp-approve</button>
      <button onClick={() => onCancel()}>pp-cancel</button>
      <button
        onClick={() => {
          void createOrder({}, {}).then((id) => {
            document.title = id;
          });
        }}
      >
        pp-create
      </button>
    </div>
  ),
}));

import { PaypalLaunch } from "@/components/checkout/PaypalLaunch";

beforeEach(() => {
  providerOptions.length = 0;
  process.env.NEXT_PUBLIC_PAYPAL_CLIENT_ID = "test-client-id";
});

describe("PaypalLaunch", () => {
  it("calls onGatewaySuccess when the buyer approves", () => {
    const onGatewaySuccess = vi.fn();
    const onGatewayAbort = vi.fn();
    render(
      <PaypalLaunch
        data={{ order_id: "PP-1", currency: "GBP" }}
        onGatewaySuccess={onGatewaySuccess}
        onGatewayAbort={onGatewayAbort}
      />
    );
    fireEvent.click(screen.getByText("pp-approve"));
    expect(onGatewaySuccess).toHaveBeenCalled();
  });

  it("calls onGatewayAbort when the buyer cancels", () => {
    const onGatewaySuccess = vi.fn();
    const onGatewayAbort = vi.fn();
    render(
      <PaypalLaunch
        data={{ order_id: "PP-1", currency: "GBP" }}
        onGatewaySuccess={onGatewaySuccess}
        onGatewayAbort={onGatewayAbort}
      />
    );
    fireEvent.click(screen.getByText("pp-cancel"));
    expect(onGatewayAbort).toHaveBeenCalled();
    expect(onGatewaySuccess).not.toHaveBeenCalled();
  });

  it("createOrder returns the SERVER-created order id — the client never prices anything", async () => {
    render(
      <PaypalLaunch data={{ order_id: "PP-42", currency: "USD" }} onGatewaySuccess={vi.fn()} onGatewayAbort={vi.fn()} />
    );
    fireEvent.click(screen.getByText("pp-create"));
    await vi.waitFor(() => expect(document.title).toBe("PP-42"));
  });

  it("loads the SDK in the ORDER's currency, not a hardcoded default", () => {
    render(
      <PaypalLaunch data={{ order_id: "PP-1", currency: "CAD" }} onGatewaySuccess={vi.fn()} onGatewayAbort={vi.fn()} />
    );
    expect(providerOptions[0]).toMatchObject({ clientId: "test-client-id", currency: "CAD", intent: "capture" });
  });

  it("falls back to USD when the response carries no currency", () => {
    render(<PaypalLaunch data={{ order_id: "PP-1" }} onGatewaySuccess={vi.fn()} onGatewayAbort={vi.fn()} />);
    expect(providerOptions[0]).toMatchObject({ currency: "USD" });
  });

  it("aborts instead of rendering buttons when the client id is missing", () => {
    process.env.NEXT_PUBLIC_PAYPAL_CLIENT_ID = "";
    const onGatewayAbort = vi.fn();
    render(
      <PaypalLaunch data={{ order_id: "PP-1", currency: "GBP" }} onGatewaySuccess={vi.fn()} onGatewayAbort={onGatewayAbort} />
    );
    expect(screen.queryByText("pp-approve")).not.toBeInTheDocument();
    expect(onGatewayAbort).toHaveBeenCalled();
  });

  it("aborts instead of rendering buttons when the order id is missing", () => {
    const onGatewayAbort = vi.fn();
    render(<PaypalLaunch data={{ currency: "GBP" }} onGatewaySuccess={vi.fn()} onGatewayAbort={onGatewayAbort} />);
    expect(screen.queryByText("pp-approve")).not.toBeInTheDocument();
    expect(onGatewayAbort).toHaveBeenCalled();
  });
});
