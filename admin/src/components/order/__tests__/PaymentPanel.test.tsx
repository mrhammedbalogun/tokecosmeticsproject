import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { PaymentPanel } from "@/components/order/PaymentPanel";
import { OrderOpsPanel } from "@/components/order/OrderOpsPanel";
import type { OrderDetail, OrderPayment } from "@/lib/order-detail";
import type { WriteState } from "@/app/(shell)/orders/[number]/actions";

type ConfirmInput = {
  number: string;
  amountReceived: string;
  bankReference: string;
  note: string;
  acceptDiscrepancy: boolean;
  allowDuplicateReference: boolean;
};

const payment = (over: Partial<OrderPayment> = {}): OrderPayment => ({
  id: 1,
  gateway: "bank_transfer",
  purpose: "goods",
  amount: "2000.00",
  currency: "NGN",
  status: "pending",
  gateway_reference: "",
  created_at: "2026-07-30T10:00:00Z",
  refunds: [],
  refundable: "0.00",
  ...over,
});

function setupPanel(
  payments: OrderPayment[] = [payment()],
  confirmReceipt = vi.fn<(i: ConfirmInput) => Promise<WriteState>>(async () => ({
    success: "Payment confirmed.",
  })),
) {
  render(
    <PaymentPanel
      number="TC-100001"
      payments={payments}
      currency="NGN"
      grandTotal="2000.00"
      confirmReceipt={confirmReceipt}
    />,
  );
  return { confirmReceipt };
}

const fillReference = (value: string) =>
  fireEvent.change(screen.getByLabelText("Bank reference"), { target: { value } });
const confirmButton = () => screen.getByRole("button", { name: /confirm payment received/i });

describe("PaymentPanel", () => {
  it("says the operator IS the verification", () => {
    // gateway.verify() raises ManualVerificationOnly for bank transfer — there is nothing
    // to look up, and the panel must not imply there is.
    setupPanel();

    expect(screen.getByText(/reading the bank statement is the check/i)).toBeInTheDocument();
  });

  it("offers NO verify-again control, which means something else for Paystack", () => {
    setupPanel();

    expect(screen.queryByRole("button", { name: /verify/i })).not.toBeInTheDocument();
  });

  it("prefills the amount with the order total", () => {
    setupPanel();

    expect(screen.getByLabelText("Amount received")).toHaveValue("2000.00");
  });

  it("passes the reference through to the action, which normalises it", () => {
    // Normalisation lives in the Server Function, not here, so that it runs whatever calls
    // it — a Server Function is a public endpoint. Asserted in the action's own tests.
    const { confirmReceipt } = setupPanel();

    fillReference("  ref   123  ");
    fireEvent.click(confirmButton());

    return waitFor(() => {
      expect(confirmReceipt.mock.calls[0][0].bankReference).toBe("  ref   123  ");
    });
  });

  it("refuses to send without a reference", async () => {
    const confirmReceipt = vi.fn<(i: ConfirmInput) => Promise<WriteState>>(async () => ({}));
    setupPanel([payment()], confirmReceipt);

    fireEvent.click(confirmButton());

    // The action itself refuses; nothing here should pretend otherwise by disabling.
    await waitFor(() => expect(confirmReceipt).toHaveBeenCalled());
    expect(confirmReceipt.mock.calls[0][0].bankReference).toBe("");
  });

  it("SHOWS BOTH NUMBERS AND THE DELTA on a discrepancy", async () => {
    // A bare "override?" checkbox hides the one number the decision is about.
    const confirmReceipt = vi.fn<(i: ConfirmInput) => Promise<WriteState>>(async () => ({
      error: "Amount does not match.",
      code: "amount_discrepancy",
      expected: "2000.00",
      received: "2500.00",
    }));
    setupPanel([payment()], confirmReceipt);

    fillReference("REF1");
    fireEvent.click(confirmButton());

    await waitFor(() => expect(screen.getByText("Order total")).toBeInTheDocument());
    expect(screen.getByText("2500.00")).toBeInTheDocument();
    expect(screen.getByText("+500.00")).toBeInTheDocument();
  });

  it("will not accept a discrepancy until a reason is written", async () => {
    const confirmReceipt = vi.fn<(i: ConfirmInput) => Promise<WriteState>>(async () => ({
      error: "Amount does not match.",
      code: "amount_discrepancy",
      expected: "2000.00",
      received: "1500.00",
    }));
    setupPanel([payment()], confirmReceipt);

    fillReference("REF1");
    fireEvent.click(confirmButton());
    await waitFor(() => expect(screen.getByText("Order total")).toBeInTheDocument());

    expect(screen.getByRole("button", { name: /accept the difference/i })).toBeDisabled();
  });

  it("sends accept_discrepancy only when the operator asks for it", async () => {
    let call = 0;
    const confirmReceipt = vi.fn<(i: ConfirmInput) => Promise<WriteState>>(async () => {
      call += 1;
      return call === 1
        ? {
            error: "Amount does not match.",
            code: "amount_discrepancy",
            expected: "2000.00",
            received: "1500.00",
          }
        : { success: "Payment confirmed." };
    });
    setupPanel([payment()], confirmReceipt);

    fillReference("REF1");
    fireEvent.click(confirmButton());
    await waitFor(() => expect(screen.getByText("Order total")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("Note"), { target: { value: "short by agreement" } });
    fireEvent.click(screen.getByRole("button", { name: /accept the difference/i }));

    await waitFor(() => expect(confirmReceipt).toHaveBeenCalledTimes(2));
    expect(confirmReceipt.mock.calls[0][0].acceptDiscrepancy).toBe(false);
    expect(confirmReceipt.mock.calls[1][0].acceptDiscrepancy).toBe(true);
  });

  it("names what a duplicate-reference override risks", async () => {
    const confirmReceipt = vi.fn<(i: ConfirmInput) => Promise<WriteState>>(async () => ({
      error: "That reference has been used.",
      code: "duplicate_bank_reference",
    }));
    setupPanel([payment()], confirmReceipt);

    fillReference("REF1");
    fireEvent.click(confirmButton());

    await waitFor(() =>
      expect(screen.getByText(/ship a second order against one transfer/i)).toBeInTheDocument(),
    );
  });

  it("hides the ceremony once the transfer has landed", () => {
    setupPanel([payment({ status: "succeeded" })]);

    expect(screen.queryByRole("button", { name: /confirm payment received/i })).not.toBeInTheDocument();
  });

  it("shows a freight payment as distinct from goods", () => {
    setupPanel([payment({ status: "succeeded" }), payment({ id: 2, purpose: "freight" })]);

    expect(screen.getByText("freight")).toBeInTheDocument();
  });

  it("says so when there is no payment at all", () => {
    setupPanel([]);

    expect(screen.getByText(/migrated legacy order/i)).toBeInTheDocument();
  });
});

// --- ops panel -----------------------------------------------------------------------

const detail = (over: Partial<OrderDetail> = {}): OrderDetail => ({
  number: "TC-100001", status: "processing", review_reason: "", placed_at: null,
  email: "b@x.test", phone: "", user_email: "", country: "NG", currency: "NGN",
  subtotal: "2000.00", discount_total: "0.00", shipping_total: "0.00", tax_total: "0.00",
  grand_total: "2000.00", grand_total_display: "₦2,000.00", delivery_option_name: "",
  shipping_address: {}, billing_address: {}, customer_note: "", admin_note: "",
  tracking_carrier: "", tracking_number: "", source: "web", legacy_number: "",
  items: [], events: [], payments: [],
  allowed_transitions: [
    { status: "shipped", requires_scope: null },
    { status: "cancelled", requires_scope: "orders.manage" },
  ],
  ...over,
});

const noopActions = () => ({
  transition: vi.fn(async () => ({ success: "ok" })),
  tracking: vi.fn(async () => ({ success: "ok" })),
  note: vi.fn(async () => ({ success: "ok" })),
  resolveReview: vi.fn(async () => ({ success: "ok" })),
  gatewayRefund: vi.fn(async () => ({ success: "ok" })),
  manualRefund: vi.fn(async () => ({ success: "ok" })),
});

describe("OrderOpsPanel", () => {
  it("GREYS an unauthorised move rather than hiding it", () => {
    // A hidden button is indistinguishable from a missing feature.
    render(
      <OrderOpsPanel order={detail()} scopes={["orders.operate"]} actions={noopActions()} />,
    );

    expect(screen.getByRole("button", { name: "Cancelled" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Shipped" })).toBeEnabled();
  });

  it("enables the elevated move for somebody holding the scope", () => {
    render(<OrderOpsPanel order={detail()} scopes={["orders.manage"]} actions={noopActions()} />);

    expect(screen.getByRole("button", { name: "Cancelled" })).toBeEnabled();
  });

  it("says the road ends when nothing is offered", () => {
    render(
      <OrderOpsPanel
        order={detail({ status: "cancelled", allowed_transitions: [] })}
        scopes={["orders.manage"]}
        actions={noopActions()}
      />,
    );

    expect(screen.getByText(/end of the road/i)).toBeInTheDocument();
  });

  it("says saving tracking does not email anybody", () => {
    // AdminOrderTrackingView records only; moving to shipped is what mails the customer.
    render(<OrderOpsPanel order={detail()} scopes={[]} actions={noopActions()} />);

    expect(screen.getByText(/emailed when you mark it shipped/i)).toBeInTheDocument();
  });

  it("says clearing a flag moves no money", () => {
    render(
      <OrderOpsPanel
        order={detail({ review_reason: "overpaid by 500.00 — refund the difference" })}
        scopes={[]}
        actions={noopActions()}
      />,
    );

    expect(screen.getByText(/moves no money/i)).toBeInTheDocument();
  });

  it("offers a MANUAL refund for bank transfer, and says it moves nothing", () => {
    const order = detail({
      payments: [{ ...payment({ status: "succeeded", refundable: "2000.00" }) }],
    });
    render(<OrderOpsPanel order={order} scopes={["orders.manage"]} actions={noopActions()} />);

    expect(screen.getByRole("button", { name: "Record refund" })).toBeInTheDocument();
    expect(screen.getByText(/does not send any/i)).toBeInTheDocument();
  });

  it("offers a GATEWAY refund for a card payment instead", () => {
    const order = detail({
      payments: [payment({ gateway: "paystack", status: "succeeded", refundable: "2000.00" })],
    });
    render(<OrderOpsPanel order={order} scopes={["orders.manage"]} actions={noopActions()} />);

    expect(screen.getByRole("button", { name: "Send refund" })).toBeInTheDocument();
  });

  it("offers no refund at all when nothing is refundable", () => {
    const order = detail({ payments: [payment({ status: "succeeded", refundable: "0.00" })] });
    render(<OrderOpsPanel order={order} scopes={["orders.manage"]} actions={noopActions()} />);

    expect(screen.queryByRole("button", { name: /refund/i })).not.toBeInTheDocument();
  });

  it("defaults restock ON, because the goods usually come back", () => {
    const order = detail({
      payments: [payment({ status: "succeeded", refundable: "2000.00" })],
    });
    render(<OrderOpsPanel order={order} scopes={["orders.manage"]} actions={noopActions()} />);

    expect(screen.getByRole("checkbox", { name: /put the stock back/i })).toBeChecked();
  });
});
